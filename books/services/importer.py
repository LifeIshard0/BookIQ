import csv
import io
from django.utils import timezone
from books.models import Book, ImportJob
from books.services.cleaning import run_cleaning_pipeline


# Fields we attempt to read from the CSV
CSV_FIELD_MAP = {
    # CSV column name  →  Book model field
    'title':            'title',
    'authors':          'author',
    'author':           'author',
    'isbn13':           'isbn_13',
    'isbn_13':          'isbn_13',
    'isbn':             'isbn_13',
    'description':      'description',
    'categories':       'genre',
    'genre':            'genre',
    'published_year':   'published_year',
    'num_pages':        'page_count',
    'page_count':       'page_count',
    'publisher':        'publisher',
    'thumbnail':        'cover_url',
    'cover_url':        'cover_url',
    'language':         'language',
    'average_rating':   None,   # ignored — we compute our own
    'ratings_count':    None,   # ignored
}


def _map_row(row: dict) -> dict:
    """Maps a CSV row dict to Book model fields."""
    book_data = {}
    for csv_col, model_field in CSV_FIELD_MAP.items():
        if model_field is None:
            continue
        value = row.get(csv_col, '').strip()
        if value and value.lower() not in ('nan', 'none', 'null', 'n/a', ''):
            book_data[model_field] = value
    return book_data


def _coerce_types(book_data: dict) -> dict:
    """Convert string values to correct Python types."""
    for int_field in ('published_year', 'page_count'):
        if int_field in book_data:
            try:
                book_data[int_field] = int(float(book_data[int_field]))
            except (ValueError, TypeError):
                book_data.pop(int_field, None)
    return book_data


def process_csv_import(
    file_content: bytes,
    file_name: str,
    imported_by,
    job: ImportJob
) -> ImportJob:
    """
    Reads a CSV file, cleans each row through the pipeline,
    and bulk-inserts valid books into the database.

    Handles duplicates gracefully — skips rather than crashing.
    Updates the ImportJob with counts and error log throughout.
    """
    job.status = ImportJob.Status.PROCESSING
    job.file_name = file_name
    job.save(update_fields=['status', 'file_name'])

    try:
        text = file_content.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        job.status = ImportJob.Status.FAILED
        job.error_log = [{'row': 0, 'error': f'Failed to parse CSV: {str(e)}'}]
        job.save(update_fields=['status', 'error_log'])
        return job

    job.total_rows = len(rows)
    job.save(update_fields=['total_rows'])

    books_to_create = []
    error_log = []
    seen_isbns = set()           # track within-batch duplicates
    cleaned_count = 0
    duplicate_count = 0
    failed_count = 0

    # Fetch all existing ISBNs once — avoids N+1 DB queries
    existing_isbns = set(
        Book.objects.exclude(isbn_13__isnull=True)
                    .exclude(isbn_13='')
                    .values_list('isbn_13', flat=True)
    )

    for i, row in enumerate(rows, start=1):
        try:
            # Map CSV columns → model fields
            book_data = _map_row(row)
            book_data = _coerce_types(book_data)

            if not book_data.get('title') or not book_data.get('author'):
                failed_count += 1
                error_log.append({
                    'row': i,
                    'error': 'Missing required fields: title or author',
                    'data': {'title': row.get('title', ''), 'author': row.get('authors', row.get('author', ''))}
                })
                continue

            # Run cleaning pipeline
            # Note: bulk_create bypasses pre_save signals intentionally
            # for performance, so we run the pipeline manually here
            cleaned = run_cleaning_pipeline(book_data)

            isbn = cleaned.get('isbn_13', '')

            # Check for duplicates
            if isbn and (isbn in existing_isbns or isbn in seen_isbns):
                duplicate_count += 1
                continue

            if isbn:
                seen_isbns.add(isbn)

            books_to_create.append(Book(
                title=cleaned.get('title', ''),
                author=cleaned.get('author', ''),
                isbn_13=isbn if isbn else None,
                description=cleaned.get('description', ''),
                genre=cleaned.get('genre', ''),
                published_year=cleaned.get('published_year'),
                publisher=cleaned.get('publisher', ''),
                page_count=cleaned.get('page_count'),
                language=cleaned.get('language', 'en'),
                cover_url=cleaned.get('cover_url', ''),
                normalized_title=cleaned.get('normalized_title', ''),
                normalized_author=cleaned.get('normalized_author', ''),
                quality_score=cleaned.get('quality_score', 0.0),
                genre_confidence=cleaned.get('genre_confidence', 0.0),
                is_flagged=cleaned.get('is_flagged', False),
                created_by=imported_by,
            ))
            cleaned_count += 1

            # Bulk insert every 500 rows to manage memory
            if len(books_to_create) >= 500:
                Book.objects.bulk_create(
                    books_to_create,
                    ignore_conflicts=True
                )
                existing_isbns.update(seen_isbns)
                books_to_create = []

        except Exception as e:
            failed_count += 1
            error_log.append({
                'row': i,
                'error': str(e),
                'data': {'title': row.get('title', '')}
            })

    # Insert remaining rows
    if books_to_create:
        Book.objects.bulk_create(books_to_create, ignore_conflicts=True)

    job.status = ImportJob.Status.COMPLETED
    job.cleaned_count = cleaned_count
    job.duplicate_count = duplicate_count
    job.failed_count = failed_count
    job.error_log = error_log[:100]   # cap log at 100 entries
    job.completed_at = timezone.now()
    job.save(update_fields=[
        'status', 'cleaned_count', 'duplicate_count',
        'failed_count', 'error_log', 'completed_at'
    ])

    return job

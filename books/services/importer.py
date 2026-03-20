import csv
import io
import os
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

BATCH_SIZE = 100


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


def _open_csv_text_stream(csv_source):
    """Return a text stream for a path, bytes, or file-like object."""
    if isinstance(csv_source, (str, os.PathLike)):
        return open(csv_source, 'r', encoding='utf-8', errors='replace', newline='')

    if isinstance(csv_source, (bytes, bytearray)):
        return io.TextIOWrapper(
            io.BytesIO(csv_source),
            encoding='utf-8',
            errors='replace',
            newline=''
        )

    if hasattr(csv_source, 'read'):
        if isinstance(getattr(csv_source, 'mode', ''), str) and 'b' in csv_source.mode:
            return io.TextIOWrapper(
                csv_source,
                encoding='utf-8',
                errors='replace',
                newline=''
            )
        return csv_source

    raise TypeError('csv_source must be a file path, bytes, or file-like object')


def _truncate_for_book_field(value, field_name: str):
    if value is None:
        return value

    field = Book._meta.get_field(field_name)
    max_length = getattr(field, 'max_length', None)

    if max_length and isinstance(value, str):
        return value[:max_length]

    return value


def process_csv_import(
    file_content,
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
        text_stream = _open_csv_text_stream(file_content)
        reader = csv.DictReader(text_stream)
    except Exception as e:
        job.status = ImportJob.Status.FAILED
        job.error_log = [{'row': 0, 'error': f'Failed to parse CSV: {str(e)}'}]
        job.save(update_fields=['status', 'error_log'])
        return job

    books_to_create = []
    error_log = []
    seen_isbns = set()           # track within-batch duplicates
    cleaned_count = 0
    duplicate_count = 0
    failed_count = 0
    total_rows = 0

    # Fetch all existing ISBNs once — avoids N+1 DB queries
    existing_isbns = set(
        Book.objects.exclude(isbn_13__isnull=True)
                    .exclude(isbn_13='')
                    .values_list('isbn_13', flat=True)
    )
    duplicate_candidates = list(
        Book.objects.only('id', 'normalized_title', 'normalized_author')[:500]
    )

    try:
        for row_number, row in enumerate(reader, start=1):
            total_rows = row_number

            try:
                # Map CSV columns → model fields
                book_data = _map_row(row)
                book_data = _coerce_types(book_data)

                if not book_data.get('title') or not book_data.get('author'):
                    failed_count += 1
                    if len(error_log) < 100:
                        error_log.append({
                            'row': row_number,
                            'error': 'Missing required fields: title or author',
                            'data': {
                                'title': row.get('title', ''),
                                'author': row.get('authors', row.get('author', ''))
                            }
                        })
                    continue

                # Run cleaning pipeline
                # Note: bulk_create bypasses pre_save signals intentionally
                # for performance, so we run the pipeline manually here
                cleaned = run_cleaning_pipeline(
                    book_data,
                    duplicate_candidates=duplicate_candidates
                )

                isbn = cleaned.get('isbn_13', '')

                # Check for duplicates
                if isbn and (isbn in existing_isbns or isbn in seen_isbns):
                    duplicate_count += 1
                    continue

                if isbn:
                    seen_isbns.add(isbn)

                books_to_create.append(Book(
                    title=_truncate_for_book_field(cleaned.get('title', ''), 'title'),
                    author=_truncate_for_book_field(cleaned.get('author', ''), 'author'),
                    isbn_13=_truncate_for_book_field(isbn if isbn else None, 'isbn_13'),
                    description=cleaned.get('description', ''),
                    genre=_truncate_for_book_field(cleaned.get('genre', ''), 'genre'),
                    published_year=cleaned.get('published_year'),
                    publisher=_truncate_for_book_field(cleaned.get('publisher', ''), 'publisher'),
                    page_count=cleaned.get('page_count'),
                    language=_truncate_for_book_field(cleaned.get('language', 'en'), 'language'),
                    cover_url=_truncate_for_book_field(cleaned.get('cover_url', ''), 'cover_url'),
                    normalized_title=_truncate_for_book_field(cleaned.get('normalized_title', ''), 'normalized_title'),
                    normalized_author=_truncate_for_book_field(cleaned.get('normalized_author', ''), 'normalized_author'),
                    quality_score=cleaned.get('quality_score', 0.0),
                    genre_confidence=cleaned.get('genre_confidence', 0.0),
                    is_flagged=cleaned.get('is_flagged', False),
                    created_by=imported_by,
                ))
                cleaned_count += 1

                # Bulk insert every 500 rows to keep memory bounded
                if len(books_to_create) >= BATCH_SIZE:
                    Book.objects.bulk_create(
                        books_to_create,
                        ignore_conflicts=True,
                        batch_size=BATCH_SIZE
                    )
                    existing_isbns.update(seen_isbns)
                    seen_isbns.clear()
                    books_to_create = []

            except Exception as e:
                failed_count += 1
                if len(error_log) < 100:
                    error_log.append({
                        'row': row_number,
                        'error': str(e),
                        'data': {'title': row.get('title', '')}
                    })

        # Insert remaining rows
        if books_to_create:
            Book.objects.bulk_create(
                books_to_create,
                ignore_conflicts=True,
                batch_size=BATCH_SIZE
            )
    finally:
        close_stream = getattr(text_stream, 'close', None)
        if callable(close_stream):
            close_stream()

    job.status = ImportJob.Status.COMPLETED
    job.total_rows = total_rows
    job.cleaned_count = cleaned_count
    job.duplicate_count = duplicate_count
    job.failed_count = failed_count
    job.error_log = error_log
    job.completed_at = timezone.now()
    job.save(update_fields=[
        'status', 'total_rows', 'cleaned_count', 'duplicate_count',
        'failed_count', 'error_log', 'completed_at'
    ])

    return job

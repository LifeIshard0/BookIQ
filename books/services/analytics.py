from django.db.models import Avg, Count, F, FloatField, Q
from django.db.models.functions import TruncMonth, Coalesce
from django.utils import timezone
from datetime import timedelta
import math


def get_genre_trends(months: int = 12) -> list:
    """
    Computes per-genre, per-month rating trends over the last N months.

    Uses TruncMonth to group BookRating records by calendar month,
    then aggregates average rating and rating count per genre.

    Steps:
    1. Filter ratings to the last `months` calendar months
    2. Annotate each rating with its book's genre and truncated month
    3. Group by (genre, month) using values() + annotate()
    4. Order by genre ASC, month ASC

    Args:
        months: number of months to look back (default 12)

    Returns:
        List of dicts with keys:
          genre, month (ISO string), avg_rating, rating_count
    """
    from books.models import BookRating

    cutoff = timezone.now() - timedelta(days=months * 30)

    trends = (
        BookRating.objects
        .filter(created_at__gte=cutoff)
        .annotate(
            genre=F('book__genre'),
            month=TruncMonth('created_at')
        )
        .values('genre', 'month')
        .annotate(
            avg_rating=Avg('rating'),
            rating_count=Count('id')
        )
        .filter(genre__isnull=False)
        .order_by('genre', 'month')
    )

    return [
        {
            'genre': row['genre'],
            'month': row['month'].strftime('%Y-%m') if row['month'] else None,
            'avg_rating': round(float(row['avg_rating']), 2)
            if row['avg_rating'] else None,
            'rating_count': row['rating_count'],
        }
        for row in trends
    ]


def get_top_genres_by_quality(limit: int = 10) -> list:
    """
    Ranks genres by average quality score across all books.

    Useful for identifying which genres have the most
    complete, validated metadata in the catalogue.

    Returns:
        List of dicts: genre, book_count, avg_quality_score,
                       flagged_count, flagged_pct
    """
    from books.models import Book

    results = (
        Book.objects
        .filter(genre__isnull=False)
        .exclude(genre='')
        .values('genre')
        .annotate(
            book_count=Count('id'),
            avg_quality=Avg('quality_score'),
            flagged_count=Count('id', filter=Q(is_flagged=True))
        )
        .filter(book_count__gte=5)
        .order_by('-avg_quality')[:limit]
    )

    return [
        {
            'genre': row['genre'],
            'book_count': row['book_count'],
            'avg_quality_score': round(float(row['avg_quality']), 3)
            if row['avg_quality'] else None,
            'flagged_count': row['flagged_count'],
            'flagged_pct': round(
                (row['flagged_count'] / row['book_count']) * 100, 1
            ) if row['book_count'] > 0 else 0.0,
        }
        for row in results
    ]


def get_catalogue_summary() -> dict:
    """
    Computes a snapshot of catalogue health metrics.

    Includes:
    - Total books, flagged books, flagged percentage
    - Average quality score across all books
    - Genre distribution (book count per genre)
    - Rating statistics (total ratings, avg rating, most rated books)
    - Import job history summary
    - Top 5 books by Wilson Score
    - Top 5 most recently added books

    Returns:
        dict with all above metrics
    """
    from books.models import Book, BookRating, ImportJob
    from books.services.search import wilson_score_lower_bound

    total_books = Book.objects.count()
    flagged_books = Book.objects.filter(is_flagged=True).count()
    avg_quality = Book.objects.aggregate(
        avg=Avg('quality_score')
    )['avg'] or 0.0

    # Genre distribution
    genre_dist = (
        Book.objects
        .exclude(genre='')
        .filter(genre__isnull=False)
        .values('genre')
        .annotate(count=Count('id'))
        .order_by('-count')[:15]
    )

    # Rating statistics
    total_ratings = BookRating.objects.count()
    avg_rating_overall = BookRating.objects.aggregate(
        avg=Avg('rating')
    )['avg'] or 0.0

    # Top 5 most rated books
    most_rated = (
        Book.objects
        .filter(rating_count__gte=1)
        .order_by('-rating_count')[:5]
        .values('id', 'title', 'genre', 'rating_count', 'average_rating')
    )

    # Top 5 by Wilson Score
    wilson_candidates = Book.objects.filter(
        rating_count__gte=5
    ).order_by('-average_rating', '-rating_count')[:100]

    wilson_scored = sorted(
        [
            {
                'id': str(book.id),
                'title': book.title,
                'genre': book.genre,
                'average_rating': book.average_rating,
                'rating_count': book.rating_count,
                'wilson_score': wilson_score_lower_bound(
                    book.upvote_count,
                    book.upvote_count + book.downvote_count
                )
            }
            for book in wilson_candidates
        ],
        key=lambda x: x['wilson_score'],
        reverse=True
    )[:5]

    # Import job summary
    import_summary = ImportJob.objects.aggregate(
        total_jobs=Count('id'),
        total_imported=Count(
            'id',
            filter=Q(status='completed')
        ),
        total_books_imported=Coalesce(
            Count('id', filter=Q(status='completed')),
            0
        )
    )

    # Quality band distribution
    quality_bands = {
        'excellent (0.8–1.0)': Book.objects.filter(
            quality_score__gte=0.8
        ).count(),
        'good (0.6–0.8)': Book.objects.filter(
            quality_score__gte=0.6,
            quality_score__lt=0.8
        ).count(),
        'fair (0.4–0.6)': Book.objects.filter(
            quality_score__gte=0.4,
            quality_score__lt=0.6
        ).count(),
        'poor (0.0–0.4)': Book.objects.filter(
            quality_score__lt=0.4
        ).count(),
    }

    # Recent additions
    recent_books = (
        Book.objects
        .order_by('-created_at')[:5]
        .values('id', 'title', 'genre', 'quality_score', 'created_at')
    )

    return {
        'catalogue_health': {
            'total_books': total_books,
            'flagged_books': flagged_books,
            'flagged_pct': round(
                (flagged_books / total_books) * 100, 1
            ) if total_books > 0 else 0.0,
            'avg_quality_score': round(float(avg_quality), 3),
            'quality_bands': quality_bands,
        },
        'genre_distribution': [
            {'genre': row['genre'], 'count': row['count']}
            for row in genre_dist
        ],
        'rating_statistics': {
            'total_ratings': total_ratings,
            'avg_rating_overall': round(float(avg_rating_overall), 2),
            'most_rated_books': [
                {
                    'id': str(row['id']),
                    'title': row['title'],
                    'genre': row['genre'],
                    'rating_count': row['rating_count'],
                    'average_rating': row['average_rating'],
                }
                for row in most_rated
            ],
        },
        'top_books_by_wilson_score': wilson_scored,
        'import_history': {
            'total_import_jobs': import_summary['total_jobs'],
            'completed_jobs': import_summary['total_imported'],
        },
        'recent_additions': [
            {
                'id': str(row['id']),
                'title': row['title'],
                'genre': row['genre'],
                'quality_score': round(float(row['quality_score']), 3)
                if row['quality_score'] else None,
                'created_at': row['created_at'].isoformat()
                if row['created_at'] else None,
            }
            for row in recent_books
        ],
        'generated_at': timezone.now().isoformat(),
    }

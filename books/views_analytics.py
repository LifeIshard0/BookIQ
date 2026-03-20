from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from books.permissions import IsAdminRole
from books.services.analytics import (
    get_genre_trends,
    get_top_genres_by_quality,
    get_catalogue_summary,
)

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes


@extend_schema(
    tags=['analytics'],
    summary='Genre rating trends',
    description=(
        'Per-genre, per-month average rating trends. '
        'Uses TruncMonth to group BookRating records by calendar month. '
        'Admin only.'
    ),
    parameters=[
        OpenApiParameter('months', OpenApiTypes.INT, description='Lookback window in months (default 12, max 24)'),
    ],
    responses={
        200: OpenApiResponse(description='List of (genre, month, avg_rating, rating_count) datapoints'),
        401: OpenApiResponse(description='Authentication required'),
        403: OpenApiResponse(description='Admin role required'),
    },
)
@api_view(['GET'])
@permission_classes([IsAdminRole])
def genre_trends(request):
    """
    GET /api/analytics/genre-trends/?months=12

    Returns per-genre, per-month rating trends.
    Groups BookRating records by (book__genre, TruncMonth(created_at)).

    Params:
      months — integer, how many months to look back (default 12, max 24)

    Response structure:
      {
        "months": 12,
        "total_datapoints": N,
        "trends": [
          {
            "genre": "Fiction",
            "month": "2025-09",
            "avg_rating": 4.2,
            "rating_count": 17
          },
          ...
        ]
      }
    """
    try:
        months = min(24, max(1, int(request.GET.get('months', 12))))
    except ValueError:
        months = 12

    trends = get_genre_trends(months=months)

    return Response({
        'months': months,
        'total_datapoints': len(trends),
        'trends': trends,
    })


@extend_schema(
    tags=['analytics'],
    summary='Genre quality ranking',
    description=(
        'Genres ranked by average metadata quality score. '
        'Identifies which genres need curator attention. '
        'Admin only.'
    ),
    parameters=[
        OpenApiParameter('limit', OpenApiTypes.INT, description='Number of genres to return (default 10, max 20)'),
    ],
    responses={200: OpenApiResponse(description='Genres with avg quality, book count, flagged pct')},
)
@api_view(['GET'])
@permission_classes([IsAdminRole])
def genre_quality(request):
    """
    GET /api/analytics/genre-quality/?limit=10

    Returns genres ranked by average metadata quality score.
    Useful for identifying which genres need curator attention.

    Params:
      limit — integer, number of genres to return (default 10, max 20)
    """
    try:
        limit = min(20, max(1, int(request.GET.get('limit', 10))))
    except ValueError:
        limit = 10

    results = get_top_genres_by_quality(limit=limit)

    return Response({
        'limit': limit,
        'genres': results,
    })


@extend_schema(
    tags=['analytics'],
    summary='Catalogue health summary',
    description=(
        'Full catalogue health snapshot: total books, flagged %, '
        'avg quality score, quality bands, genre distribution, '
        'rating statistics, top books by Wilson Score, import history. '
        'Admin only.'
    ),
    responses={200: OpenApiResponse(description='Full catalogue health snapshot')},
)
@api_view(['GET'])
@permission_classes([IsAdminRole])
def catalogue_summary(request):
    """
    GET /api/analytics/summary/

    Returns a full catalogue health snapshot including:
    - Total books, flagged %, avg quality score, quality bands
    - Genre distribution (top 15)
    - Rating statistics and most-rated books
    - Top 5 books by Wilson Score Lower Bound
    - Import job history
    - 5 most recently added books

    Admin only. No query params required.
    """
    summary = get_catalogue_summary()
    return Response(summary)

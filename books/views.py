from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.db import IntegrityError

from .models import Book, BookRating, ImportJob
from .serializers import BookSerializer, BookListSerializer, BookRatingSerializer, ImportJobSerializer
from .permissions import IsCuratorOrAbove, IsAdminRole, IsReaderOrAbove

from books.services.importer import process_csv_import

from django_filters.rest_framework import DjangoFilterBackend
from .filters import BookFilter
from .pagination import BookPagination

from books.services.search import wilson_score_lower_bound


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.select_related('created_by').all()
    pagination_class = BookPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.OrderingFilter,
        filters.SearchFilter,
    ]
    filterset_class = BookFilter
    search_fields = ['title', 'author', 'genre', 'isbn_13']
    ordering_fields = [
        'created_at', 'average_rating', 'quality_score',
        'published_year', 'rating_count', 'title'
    ]
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        is_flagged = self.request.query_params.get('is_flagged')

        if is_flagged is not None:
            normalized = is_flagged.strip().lower()
            if normalized in {'true', '1', 'yes'}:
                queryset = queryset.filter(is_flagged=True)
            elif normalized in {'false', '0', 'no'}:
                queryset = queryset.filter(is_flagged=False)

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return BookListSerializer
        return BookSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        if self.action in ['create', 'update', 'partial_update']:
            return [IsCuratorOrAbove()]
        if self.action == 'destroy':
            return [IsAdminRole()]
        if self.action == 'recommendations':
            return [IsReaderOrAbove()]
        return [IsAuthenticatedOrReadOnly()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError:
            return Response(
                {
                    'error': True,
                    'status_code': 409,
                    'detail': 'A book with this ISBN-13 already exists.'
                },
                status=status.HTTP_409_CONFLICT
            )
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {'message': f"Book '{instance.title}' deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsReaderOrAbove],
        url_path='rate'
    )
    def rate(self, request, pk=None):
        """POST /api/books/{id}/rate/ — create or update a rating (upsert)."""
        book = self.get_object()
        serializer = BookRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rating_obj, created = BookRating.objects.update_or_create(
            book=book,
            user=request.user,
            defaults={
                'rating': serializer.validated_data['rating'],
                'review': serializer.validated_data.get('review', ''),
            }
        )

        response_serializer = BookRatingSerializer(rating_obj)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(response_serializer.data, status=status_code)

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[AllowAny],
        url_path='ratings'
    )
    def ratings(self, request, pk=None):
        """GET /api/books/{id}/ratings/ — list all ratings for a book."""
        book = self.get_object()
        ratings = book.ratings.select_related('user').all()
        serializer = BookRatingSerializer(ratings, many=True)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsReaderOrAbove],
        url_path='my-rating'
    )
    def my_rating(self, request, pk=None):
        """
        GET /api/books/{id}/my-rating/
        Returns the current user's rating for this book, or 404 if the user has not rated it yet.
        Useful for pre-populating rating UI without fetching all ratings.
        """
        book = self.get_object()
        try:
            rating = BookRating.objects.get(book=book, user=request.user)
            serializer = BookRatingSerializer(rating)
            return Response(serializer.data)
        except BookRating.DoesNotExist:
            return Response(
                {
                    'error': True,
                    'status_code': 404,
                    'detail': 'You have not rated this book yet.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(
        detail=False,
        methods=['get'],
        permission_classes=[AllowAny],
        url_path='search'
    )
    def search(self, request):
        """
        GET /api/books/search/?q=gatsby&genre=fiction&min_quality=0.8

        Full-text search using PostgreSQL SearchVector + SearchRank
        with GIN index. Supports websearch syntax:
        "exact phrase"   — phrase match
        word1 word2      — both words required
        word1 OR word2   — either word
        -word            — exclude word

        Additional filter params:
        genre, author, language, publisher, is_flagged,
        min_quality, max_quality, min_rating,
        published_after, published_before,
        ordering, page, page_size
        """
        from books.services.search import full_text_search

        raw_query = request.GET.get('q', '').strip()

        # Start with base queryset, apply non-search filters first
        base_qs = Book.objects.select_related('created_by').all()
        filterset = BookFilter(request.GET, queryset=base_qs)

        if not filterset.is_valid():
            return Response(
                {'error': True, 'status_code': 400, 'detail': filterset.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        filtered_qs = filterset.qs

        # If a query is provided, apply FTS on top of the filtered queryset
        if raw_query:
            # Remove keyword filter from filterset (we handle it via FTS)
            # FTS returns annotated queryset with .rank and .headline
            results_qs = full_text_search(raw_query, queryset=filtered_qs)
            use_fts = True
        else:
            # No query — return filtered list ordered by average_rating
            ordering = request.GET.get('ordering', '-average_rating')
            allowed_orderings = [
                'created_at', '-created_at',
                'average_rating', '-average_rating',
                'quality_score', '-quality_score',
                'published_year', '-published_year',
                'rating_count', '-rating_count',
                'title', '-title',
            ]
            results_qs = filtered_qs.order_by(
                ordering if ordering in allowed_orderings else '-average_rating'
            )
            use_fts = False

        # Paginate
        paginator = BookPagination()
        page = paginator.paginate_queryset(results_qs, request)

        if page is not None:
            serializer = BookListSerializer(page, many=True)
            response_data = paginator.get_paginated_response(serializer.data).data

            # Add FTS metadata to response
            response_data['query'] = raw_query
            response_data['search_type'] = 'full_text_search' if use_fts else 'filter_only'
            response_data['filters_applied'] = {
                k: v for k, v in request.GET.items()
                if k not in ('page', 'page_size', 'ordering', 'q')
            }

            # If FTS — include rank and headline in results
            if use_fts and page:
                for i, book in enumerate(page):
                    if hasattr(book, 'rank'):
                        response_data['results'][i]['rank'] = round(
                            float(book.rank), 4
                        )
                    if hasattr(book, 'headline'):
                        response_data['results'][i]['headline'] = book.headline

            return Response(response_data)

        serializer = BookListSerializer(results_qs, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[AllowAny],
        url_path='hybrid-search'
    )
    def hybrid_search(self, request):
        """
        GET /api/books/hybrid-search/?q=gatsby

        Blends PostgreSQL FTS (relevance) with Wilson Score popularity
        using Reciprocal Rank Fusion (Cormack et al., 2009).

        RRF score = fts_weight*(1/(k+fts_rank)) + pop_weight*(1/(k+pop_rank))
        where k=60 (standard constant).

        Additional params:
        fts_weight       — float 0.0–1.0, default 0.7
        popularity_weight — float 0.0–1.0, default 0.3
        page, page_size  — pagination
        All BookFilter params also supported
        """
        from books.services.search import hybrid_search as run_hybrid_search

        raw_query = request.GET.get('q', '').strip()

        if not raw_query:
            return Response(
                {
                    'error': True,
                    'status_code': 400,
                    'detail': 'A search query (?q=) is required for hybrid search.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Parse weights from query params
        try:
            fts_weight = float(request.GET.get('fts_weight', 0.7))
            popularity_weight = float(request.GET.get('popularity_weight', 0.3))
            if not (0.0 <= fts_weight <= 1.0 and 0.0 <= popularity_weight <= 1.0):
                raise ValueError
        except ValueError:
            return Response(
                {
                    'error': True,
                    'status_code': 400,
                    'detail': 'fts_weight and popularity_weight must be floats between 0.0 and 1.0.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Apply non-search filters
        base_qs = Book.objects.select_related('created_by').all()
        filterset = BookFilter(request.GET, queryset=base_qs)
        if not filterset.is_valid():
            return Response(
                {'error': True, 'status_code': 400, 'detail': filterset.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            page = max(1, int(request.GET.get('page', 1)))
            page_size = min(100, max(1, int(request.GET.get('page_size', 20))))
        except ValueError:
            page, page_size = 1, 20

        result = run_hybrid_search(
            raw_query=raw_query,
            queryset=filterset.qs,
            page=page,
            page_size=page_size,
            fts_weight=fts_weight,
            popularity_weight=popularity_weight,
        )

        # Serialise results
        serialised_results = []
        for book, rrf_score in result['results']:
            data = BookListSerializer(book).data
            data['rrf_score'] = rrf_score
            data['wilson_score'] = wilson_score_lower_bound(
                book.upvote_count,
                book.upvote_count + book.downvote_count
            )
            if hasattr(book, 'rank'):
                data['fts_rank'] = round(float(book.rank), 4)
            serialised_results.append(data)

        return Response({
            'query': result['query'],
            'count': result['count'],
            'page': result['page'],
            'page_size': result['page_size'],
            'total_pages': result['total_pages'],
            'fts_weight': result['fts_weight'],
            'popularity_weight': result['popularity_weight'],
            'search_type': 'hybrid_rrf',
            'results': serialised_results,
        })

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsReaderOrAbove],
        url_path='recommendations'
    )
    def recommendations(self, request):
        """
        GET /api/books/recommendations/

        Returns personalised book recommendations for the
        authenticated user.

        Strategy waterfall (automatic):
        1. content_based      — genre/author profile from liked books
        2. collaborative      — Jaccard similarity with similar users
        3. popularity_wilson  — cold-start Wilson Score fallback

        Optional params:
        limit      — number of results (default 20, max 50)
        strategy   — force a specific strategy:
                    content_based | collaborative | popularity
        """
        from books.services.recommender import (
            get_recommendations,
            content_based_recommendations,
            collaborative_recommendations,
            popularity_recommendations,
            build_taste_profile,
        )

        try:
            limit = min(50, max(1, int(request.GET.get('limit', 20))))
        except ValueError:
            limit = 20

        forced_strategy = request.GET.get('strategy', '').strip().lower()

        if forced_strategy == 'content_based':
            results, strategy = content_based_recommendations(
                request.user, limit=limit
            )
        elif forced_strategy == 'collaborative':
            results, strategy = collaborative_recommendations(
                request.user, limit=limit
            )
        elif forced_strategy == 'popularity':
            profile = build_taste_profile(request.user)
            results, strategy = popularity_recommendations(
                limit=limit,
                exclude_ids=profile['all_rated_ids']
            )
        else:
            results, strategy = get_recommendations(request.user, limit=limit)

        serializer = BookListSerializer(results, many=True)

        # Build profile summary for response metadata
        profile = build_taste_profile(request.user)
        top_genres = [
            g for g, _ in profile['liked_genres'].most_common(3)
        ]
        top_authors = [
            a for a, _ in profile['liked_authors'].most_common(3)
        ]

        return Response({
            'recommendation_strategy': strategy,
            'count': len(results),
            'limit': limit,
            'profile_summary': {
                'total_ratings': len(profile['all_rated_ids']),
                'liked_books': len(profile['liked_book_ids']),
                'top_genres': top_genres,
                'top_authors': top_authors,
            },
            'results': serializer.data,
        })


class ImportJobViewSet(viewsets.GenericViewSet):
    """
    POST /api/imports/        — upload CSV, triggers import, returns job
    GET  /api/imports/        — list all import jobs (admin only)
    GET  /api/imports/{id}/   — check status of a specific import job
    """
    serializer_class = ImportJobSerializer
    permission_classes = [IsAdminRole]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return ImportJob.objects.filter(
            created_by=self.request.user
        ).order_by('-created_at')

    def list(self, request):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        job = get_object_or_404(ImportJob, pk=pk, created_by=request.user)
        serializer = self.get_serializer(job)
        return Response(serializer.data)

    def create(self, request):
        if 'file' not in request.FILES:
            return Response(
                {'error': True, 'detail': 'No file uploaded. Send a CSV as multipart/form-data with key "file".'},
                status=status.HTTP_400_BAD_REQUEST
            )

        uploaded_file = request.FILES['file']

        if not uploaded_file.name.endswith('.csv'):
            return Response(
                {'error': True, 'detail': 'Only CSV files are accepted.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if uploaded_file.size > 50 * 1024 * 1024:  # 50MB limit
            return Response(
                {'error': True, 'detail': 'File too large. Maximum size is 50MB.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the job record immediately — return it to the client
        job = ImportJob.objects.create(
            status=ImportJob.Status.PENDING,
            file_name=uploaded_file.name,
            created_by=request.user,
        )

        # Process synchronously (no Celery for coursework)
        # In production this would be: process_csv_import.delay(...)
        process_csv_import(
            file_content=uploaded_file,
            file_name=uploaded_file.name,
            imported_by=request.user,
            job=job,
        )

        job.refresh_from_db()
        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class RatingViewSet(viewsets.GenericViewSet):
    """
    Dedicated endpoints for a user's own ratings.

    GET  /api/ratings/           — list all of my ratings
    GET  /api/ratings/{id}/      — retrieve one of my ratings
    PATCH /api/ratings/{id}/     — update my rating
    DELETE /api/ratings/{id}/    — delete my rating
    """
    serializer_class = BookRatingSerializer
    permission_classes = [IsReaderOrAbove]

    def get_queryset(self):
        # Users can only see and manage their own ratings
        return BookRating.objects.filter(
            user=self.request.user
        ).select_related('book', 'user').order_by('-created_at')

    def list(self, request):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        rating = get_object_or_404(
            BookRating,
            pk=pk,
            user=request.user
        )
        serializer = self.get_serializer(rating)
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        rating = get_object_or_404(
            BookRating,
            pk=pk,
            user=request.user
        )
        serializer = self.get_serializer(
            rating,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        rating = get_object_or_404(
            BookRating,
            pk=pk,
            user=request.user
        )
        book_title = rating.book.title
        rating.delete()
        # Signal fires automatically — book aggregates updated
        return Response(
            {'message': f"Rating for '{book_title}' deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )


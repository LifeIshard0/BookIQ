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


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.select_related('created_by').all()
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    search_fields = ['title', 'author', 'genre', 'isbn_13']
    ordering_fields = [
        'created_at', 'average_rating',
        'quality_score', 'published_year', 'rating_count'
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


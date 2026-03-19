from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from django.shortcuts import get_object_or_404
from django.db import IntegrityError

from .models import Book, BookRating
from .serializers import BookSerializer, BookListSerializer, BookRatingSerializer
from .permissions import IsCuratorOrAbove, IsAdminRole, IsReaderOrAbove


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.select_related('created_by').all()
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    search_fields = ['title', 'author', 'genre', 'isbn_13']
    ordering_fields = [
        'created_at', 'average_rating',
        'quality_score', 'published_year', 'rating_count'
    ]
    ordering = ['-created_at']

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

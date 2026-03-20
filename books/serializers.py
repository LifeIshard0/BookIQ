from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from .models import Book, BookRating, ImportJob


class BookSerializer(serializers.ModelSerializer):
    created_by_username = serializers.SerializerMethodField()
    vote_distribution = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            'id', 'title', 'author', 'isbn_13', 'description',
            'genre', 'published_year', 'publisher', 'page_count',
            'language', 'cover_url',
            # Cleaned fields
            'normalized_title', 'normalized_author',
            # Intelligence
            'quality_score', 'is_flagged', 'genre_confidence',
            # Ratings
            'average_rating', 'rating_count',
            'upvote_count', 'downvote_count',
            # Computed
            'vote_distribution', 'created_by_username',
            # Timestamps
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'normalized_title', 'normalized_author',
            'quality_score', 'is_flagged', 'genre_confidence',
            'average_rating', 'rating_count',
            'upvote_count', 'downvote_count',
            'created_by_username', 'vote_distribution',
            'created_at', 'updated_at',
        ]
        extra_kwargs = {
            'isbn_13': {'validators': []},
        }

    @extend_schema_field(OpenApiTypes.STR)
    def get_created_by_username(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_vote_distribution(self, obj):
        total = obj.upvote_count + obj.downvote_count
        if total == 0:
            return {'upvote_ratio': 0.0, 'downvote_ratio': 0.0}
        return {
            'upvote_ratio': round(obj.upvote_count / total, 3),
            'downvote_ratio': round(obj.downvote_count / total, 3),
        }

    def validate_isbn_13(self, value):
        if not value:
            return value
        digits = value.replace('-', '').replace(' ', '')
        if not digits.isdigit() or len(digits) != 13:
            raise serializers.ValidationError(
                'ISBN-13 must be exactly 13 digits.'
            )
        return digits

    def validate_published_year(self, value):
        if value is not None and (value < 1000 or value > 2100):
            raise serializers.ValidationError(
                'Published year must be between 1000 and 2100.'
            )
        return value

    def validate_page_count(self, value):
        if value is not None and value < 1:
            raise serializers.ValidationError(
                'Page count must be a positive integer.'
            )
        return value


class BookListSerializer(serializers.ModelSerializer):
    """Lighter serializer for list views — fewer fields for performance."""

    class Meta:
        model = Book
        fields = [
            'id', 'title', 'author', 'genre', 'isbn_13',
            'published_year', 'quality_score', 'is_flagged',
            'average_rating', 'rating_count', 'cover_url',
            'normalized_title', 'normalized_author',
        ]


class BookRatingSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    vote_type = serializers.SerializerMethodField()
    book_title = serializers.SerializerMethodField()

    class Meta:
        model = BookRating
        fields = [
            'id', 'book', 'book_title', 'rating', 'review',
            'vote_type', 'username', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'book', 'book_title', 'username',
            'vote_type', 'created_at', 'updated_at'
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_username(self, obj):
        return obj.user.username

    @extend_schema_field(OpenApiTypes.STR)
    def get_vote_type(self, obj):
        return obj.vote_type
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_book_title(self, obj):
        return obj.book.title

    def validate_rating(self, value):
        if value not in range(1, 6):
            raise serializers.ValidationError(
                'Rating must be an integer between 1 and 5.'
            )
        return value


class ImportJobSerializer(serializers.ModelSerializer):
    created_by_username = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            'id', 'status', 'file_name',
            'total_rows', 'cleaned_count',
            'duplicate_count', 'failed_count',
            'error_log', 'progress_percent',
            'created_by_username',
            'created_at', 'completed_at',
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_created_by_username(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return None

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_progress_percent(self, obj):
        if obj.total_rows == 0:
            return 0
        processed = obj.cleaned_count + obj.duplicate_count + obj.failed_count
        return round((processed / obj.total_rows) * 100, 1)

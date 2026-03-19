from django.contrib import admin
from .models import Book, BookRating, ImportJob


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'author', 'genre', 'quality_score',
        'is_flagged', 'average_rating', 'rating_count', 'created_at'
    )
    list_filter = ('genre', 'is_flagged', 'language')
    search_fields = ('title', 'author', 'isbn_13')
    readonly_fields = (
        'id', 'normalized_title', 'normalized_author',
        'quality_score', 'is_flagged', 'average_rating',
        'rating_count', 'upvote_count', 'downvote_count',
        'created_at', 'updated_at'
    )
    fieldsets = (
        ('Core Metadata', {
            'fields': ('title', 'author', 'isbn_13', 'genre',
                       'published_year', 'publisher', 'page_count',
                       'language', 'cover_url', 'description')
        }),
        ('Cleaned Fields', {
            'fields': ('normalized_title', 'normalized_author'),
            'classes': ('collapse',)
        }),
        ('Intelligence', {
            'fields': ('quality_score', 'is_flagged', 'genre_confidence'),
            'classes': ('collapse',)
        }),
        ('Ratings', {
            'fields': ('average_rating', 'rating_count',
                       'upvote_count', 'downvote_count'),
            'classes': ('collapse',)
        }),
        ('Provenance', {
            'fields': ('id', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(BookRating)
class BookRatingAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'rating', 'vote_type', 'created_at')
    list_filter = ('rating',)
    search_fields = ('user__username', 'book__title')
    readonly_fields = ('id', 'created_at', 'updated_at', 'vote_type')


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'status', 'file_name', 'total_rows',
        'cleaned_count', 'duplicate_count', 'failed_count', 'created_at'
    )
    list_filter = ('status',)
    readonly_fields = (
        'id', 'cleaned_count', 'duplicate_count',
        'failed_count', 'error_log', 'created_at', 'completed_at'
    )

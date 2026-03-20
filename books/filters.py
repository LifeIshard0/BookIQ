import django_filters
from .models import Book


class BookFilter(django_filters.FilterSet):
    # Keyword search across title, author, genre
    q = django_filters.CharFilter(method='filter_keyword', label='Keyword search')

    # Exact and partial filters
    genre = django_filters.CharFilter(
        field_name='genre',
        lookup_expr='icontains',
        label='Genre (partial match)'
    )
    author = django_filters.CharFilter(
        field_name='normalized_author',
        lookup_expr='icontains',
        label='Author (partial match)'
    )
    language = django_filters.CharFilter(
        field_name='language',
        lookup_expr='iexact',
        label='Language code (e.g. en)'
    )
    publisher = django_filters.CharFilter(
        field_name='publisher',
        lookup_expr='icontains',
        label='Publisher (partial match)'
    )

    # Boolean filters
    is_flagged = django_filters.BooleanFilter(
        field_name='is_flagged',
        label='Is flagged for review'
    )

    # Range filters
    min_quality = django_filters.NumberFilter(
        field_name='quality_score',
        lookup_expr='gte',
        label='Minimum quality score (0.0 - 1.0)'
    )
    max_quality = django_filters.NumberFilter(
        field_name='quality_score',
        lookup_expr='lte',
        label='Maximum quality score (0.0 - 1.0)'
    )
    min_rating = django_filters.NumberFilter(
        field_name='average_rating',
        lookup_expr='gte',
        label='Minimum average rating (1 - 5)'
    )
    published_after = django_filters.NumberFilter(
        field_name='published_year',
        lookup_expr='gte',
        label='Published year from'
    )
    published_before = django_filters.NumberFilter(
        field_name='published_year',
        lookup_expr='lte',
        label='Published year to'
    )

    class Meta:
        model = Book
        fields = [
            'q', 'genre', 'author', 'language', 'publisher',
            'is_flagged', 'min_quality', 'max_quality',
            'min_rating', 'published_after', 'published_before',
        ]

    def filter_keyword(self, queryset, name, value):
        """
        Multi-field keyword search using OR logic across:
        - normalized_title
        - normalized_author
        - genre
        - description
        - isbn_13
        Each field uses icontains (case-insensitive substring match).
        """
        if not value:
            return queryset
        from django.db.models import Q
        return queryset.filter(
            Q(normalized_title__icontains=value) |
            Q(normalized_author__icontains=value) |
            Q(genre__icontains=value) |
            Q(description__icontains=value) |
            Q(isbn_13__icontains=value)
        ).distinct()

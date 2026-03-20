from django.contrib.postgres.search import (
    SearchVector,
    SearchQuery,
    SearchRank,
    SearchHeadline,
)
from django.db.models import F
from books.models import Book


# Weights: D (lowest) → C → B → A (highest)
# PostgreSQL default weights: D=0.1, C=0.2, B=0.4, A=1.0
SEARCH_VECTOR = (
    SearchVector('normalized_title', weight='A', config='english') +
    SearchVector('normalized_author', weight='B', config='english') +
    SearchVector('genre', weight='C', config='english') +
    SearchVector('description', weight='D', config='english')
)


def build_search_query(raw_query: str) -> SearchQuery:
    """
    Parses the raw query string using PostgreSQL websearch syntax.

    websearch_to_tsquery supports:
      "exact phrase"     — phrase search
      word1 word2        — both words must appear (AND)
      word1 OR word2     — either word
      -word              — exclude word
      word:*             — prefix search

    Falls back to plain search if websearch parsing fails.
    """
    try:
        return SearchQuery(raw_query, search_type='websearch', config='english')
    except Exception:
        return SearchQuery(raw_query, search_type='plain', config='english')


def full_text_search(
    raw_query: str,
    queryset=None,
    min_rank: float = 0.01
):
    """
    Executes a ranked PostgreSQL full-text search against the
    pre-built search_vector field (GIN-indexed).

    Steps:
    1. Build SearchQuery from raw_query using websearch syntax
    2. Filter by search_vector match (uses GIN index — fast)
    3. Annotate each result with SearchRank score
    4. Annotate with SearchHeadline for highlighted snippets
    5. Filter out results below min_rank threshold
    6. Order by rank descending

    Args:
        raw_query:  user-supplied search string
        queryset:   optional pre-filtered queryset (for combining with other filters)
        min_rank:   minimum rank threshold (filters noise)

    Returns:
        Annotated queryset with .rank and .headline fields
    """
    if queryset is None:
        queryset = Book.objects.all()

    if not raw_query or not raw_query.strip():
        return queryset.none()

    query = build_search_query(raw_query)

    return (
        queryset
        .filter(search_vector=query)
        .annotate(
            rank=SearchRank(
                F('search_vector'),
                query,
                weights=[0.1, 0.2, 0.4, 1.0],   # D, C, B, A
                normalization=2                    # divide by document length
            ),
            headline=SearchHeadline(
                'description',
                query,
                config='english',
                start_sel='<mark>',
                stop_sel='</mark>',
                max_words=20,
                min_words=10,
                max_fragments=2,
            )
        )
        .filter(rank__gte=min_rank)
        .order_by('-rank')
    )


def rebuild_search_vector(book: Book) -> None:
    """
    Rebuilds the search_vector for a single Book instance.
    Called by the post_save signal.
    Uses update() to avoid triggering the signal recursively.
    """
    Book.objects.filter(pk=book.pk).update(
        search_vector=SEARCH_VECTOR
    )


def rebuild_all_search_vectors() -> int:
    """
    Rebuilds search_vector for every book in the database.
    Used by the management command for initial backfill.
    Returns count of updated records.
    """
    updated = Book.objects.update(search_vector=SEARCH_VECTOR)
    return updated

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


import math


def wilson_score_lower_bound(upvotes: int, total: int, confidence: float = 0.95) -> float:
    """
    Computes the Wilson Score Lower Bound for a Bernoulli proportion.

    This is used as the popularity signal in RRF blending.
    It answers: 'Given these upvotes, what is the lowest plausible
    true upvote rate at the given confidence level?'

    A book with 5/5 upvotes scores LOWER than one with 450/500
    because the small sample provides less statistical certainty.

    Args:
        upvotes:    number of positive ratings (rating >= 4)
        total:      total number of ratings
        confidence: statistical confidence level (default 95% → z=1.96)

    Returns:
        float in [0.0, 1.0] — lower bound of Wilson confidence interval
    """
    if total == 0:
        return 0.0

    z = 1.96  # 95% confidence interval
    p = upvotes / total

    numerator = (
        p + (z ** 2) / (2 * total) -
        z * math.sqrt((p * (1 - p) / total) + (z ** 2) / (4 * total ** 2))
    )
    denominator = 1 + (z ** 2) / total

    return round(numerator / denominator, 6)


def reciprocal_rank_fusion(
    fts_results: list,
    popularity_results: list,
    k: int = 60,
    fts_weight: float = 0.7,
    popularity_weight: float = 0.3,
) -> list:
    """
    Merges two ranked result lists using Reciprocal Rank Fusion.

    RRF score for item i = weight * sum(1 / (k + rank_i))
    where rank_i is the item's position in each list (1-indexed).

    The k constant (default 60, from Cormack et al. 2009) prevents
    high-ranked items in one list from completely dominating the
    merged result — it smooths the contribution of top-ranked items.

    Args:
        fts_results:        list of Book objects ordered by FTS rank
        popularity_results: list of Book objects ordered by Wilson Score
        k:                  RRF constant (60 is the standard value)
        fts_weight:         contribution weight of FTS ranking (default 0.7)
        popularity_weight:  contribution weight of popularity (default 0.3)

    Returns:
        List of (book, rrf_score) tuples sorted by rrf_score descending
    """
    # Build rank lookup dictionaries keyed by book UUID
    fts_ranks = {book.id: rank + 1 for rank, book in enumerate(fts_results)}
    pop_ranks = {book.id: rank + 1 for rank, book in enumerate(popularity_results)}

    # Union of all book IDs from both lists
    all_ids = set(fts_ranks.keys()) | set(pop_ranks.keys())

    # Build a lookup dict for book objects
    book_lookup = {book.id: book for book in fts_results}
    book_lookup.update({book.id: book for book in popularity_results})

    scores = {}
    for book_id in all_ids:
        score = 0.0
        if book_id in fts_ranks:
            score += fts_weight * (1.0 / (k + fts_ranks[book_id]))
        if book_id in pop_ranks:
            score += popularity_weight * (1.0 / (k + pop_ranks[book_id]))
        scores[book_id] = score

    # Sort by RRF score descending
    ranked_ids = sorted(scores.keys(), key=lambda bid: scores[bid], reverse=True)
    return [(book_lookup[bid], round(scores[bid], 6)) for bid in ranked_ids]


def hybrid_search(
    raw_query: str,
    queryset=None,
    page: int = 1,
    page_size: int = 20,
    fts_weight: float = 0.7,
    popularity_weight: float = 0.3,
) -> dict:
    """
    Full hybrid search pipeline:

    1. Run PostgreSQL FTS → ranked by SearchRank (relevance)
    2. Run popularity ranking → ordered by Wilson Score Lower Bound
       on the same filtered queryset
    3. Merge both lists with RRF
    4. Paginate the merged result

    Args:
        raw_query:          user search string
        queryset:           pre-filtered Book queryset
        page:               page number (1-indexed)
        page_size:          results per page
        fts_weight:         RRF weight for FTS list (default 0.7)
        popularity_weight:  RRF weight for popularity list (default 0.3)

    Returns:
        dict with keys: results, count, page, page_size,
                        total_pages, fts_weight, popularity_weight
    """
    if queryset is None:
        from books.models import Book
        queryset = Book.objects.all()

    # --- Signal 1: FTS ranked results ---
    fts_qs = full_text_search(raw_query, queryset=queryset)
    fts_results = list(fts_qs[:200])    # cap at 200 for RRF performance

    # --- Signal 2: Popularity ranked results (Wilson Score) ---
    # Use same filtered queryset, order by Wilson-like proxy:
    # books with both high rating AND sufficient vote count
    # We approximate Wilson Score using pre-aggregated fields
    from books.models import Book as BookModel
    pop_qs = queryset.filter(
        id__in=[b.id for b in fts_results] if fts_results else []
    ).order_by('-average_rating', '-rating_count')
    popularity_results = list(pop_qs[:200])

    # Apply true Wilson Score ordering in Python
    def wilson_key(book):
        return wilson_score_lower_bound(
            book.upvote_count,
            book.upvote_count + book.downvote_count
        )

    popularity_results.sort(key=wilson_key, reverse=True)

    # --- RRF Merge ---
    if not fts_results and not popularity_results:
        return {
            'results': [],
            'count': 0,
            'page': page,
            'page_size': page_size,
            'total_pages': 0,
            'query': raw_query,
            'fts_weight': fts_weight,
            'popularity_weight': popularity_weight,
        }

    merged = reciprocal_rank_fusion(
        fts_results,
        popularity_results,
        fts_weight=fts_weight,
        popularity_weight=popularity_weight,
    )

    # --- Paginate the merged list ---
    total = len(merged)
    start = (page - 1) * page_size
    end = start + page_size
    page_results = merged[start:end]

    return {
        'results': page_results,            # list of (book, rrf_score) tuples
        'count': total,
        'page': page,
        'page_size': page_size,
        'total_pages': math.ceil(total / page_size) if total > 0 else 0,
        'query': raw_query,
        'fts_weight': fts_weight,
        'popularity_weight': popularity_weight,
    }

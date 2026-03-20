from collections import Counter, defaultdict
from books.services.search import wilson_score_lower_bound


# --- Taste Profile Builder ---

def build_taste_profile(user) -> dict:
    """
    Builds a taste profile from books the user has rated >= 4.

    Returns a dict with:
      liked_genres:   Counter of genre → frequency
      liked_authors:  Counter of author → frequency
      liked_book_ids: set of book UUIDs (to exclude from recommendations)
      all_rated_ids:  set of all rated book UUIDs (liked + disliked)
      has_ratings:    bool — False if user has never rated anything
    """
    from books.models import BookRating

    liked_ratings = BookRating.objects.filter(
        user=user,
        rating__gte=4
    ).select_related('book')

    all_rated = BookRating.objects.filter(
        user=user
    ).values_list('book_id', flat=True)

    liked_genres = Counter()
    liked_authors = Counter()
    liked_book_ids = set()

    for rating in liked_ratings:
        book = rating.book
        liked_book_ids.add(book.id)
        if book.genre:
            liked_genres[book.genre.strip()] += 1
        if book.normalized_author:
            liked_authors[book.normalized_author.strip()] += 1

    return {
        'liked_genres': liked_genres,
        'liked_authors': liked_authors,
        'liked_book_ids': liked_book_ids,
        'all_rated_ids': set(all_rated),
        'has_ratings': len(liked_book_ids) > 0,
    }


# --- Strategy 1: Content-Based Filtering ---

def content_based_recommendations(user, limit: int = 20) -> tuple:
    """
    Recommends books based on genre and author overlap with the
    user's liked books (rating >= 4).

    Scoring per candidate book:
      +3  if genre exactly matches user's most-liked genre
      +2  if genre matches any liked genre
      +2  if author exactly matches user's most-liked author
      +1  if author matches any liked author
      +0.1 * quality_score (tiebreaker — prefer cleaner records)

    Returns:
      (list of Book objects, strategy_name)
    """
    from books.models import Book

    profile = build_taste_profile(user)

    if not profile['has_ratings']:
        return [], 'no_ratings'

    top_genre = profile['liked_genres'].most_common(1)[0][0] \
        if profile['liked_genres'] else None
    top_author = profile['liked_authors'].most_common(1)[0][0] \
        if profile['liked_authors'] else None

    # Candidate pool: unrated books only
    candidates = Book.objects.exclude(
        id__in=profile['all_rated_ids']
    ).filter(
        quality_score__gte=0.4
    ).order_by('-average_rating')[:500]

    scored = []
    for book in candidates:
        score = 0.0

        # Genre scoring
        if book.genre:
            book_genre = book.genre.strip()
            if top_genre and book_genre == top_genre:
                score += 3
            elif book_genre in profile['liked_genres']:
                score += 2

        # Author scoring
        if book.normalized_author:
            book_author = book.normalized_author.strip()
            if top_author and book_author == top_author:
                score += 2
            elif book_author in profile['liked_authors']:
                score += 1

        # Quality tiebreaker
        score += 0.1 * (book.quality_score or 0.0)

        if score > 0:
            scored.append((book, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    results = [book for book, _ in scored[:limit]]

    if not results:
        return [], 'no_matches'

    return results, 'content_based'


# --- Strategy 2: Collaborative Filtering ---

def collaborative_recommendations(user, limit: int = 20) -> tuple:
    """
    User-based memory collaborative filtering.

    Steps:
    1. Find all users who have liked at least one of the same books
       as the current user (rating >= 4 on both sides)
    2. Compute Jaccard similarity: |intersection| / |union| of
       their liked book sets
    3. Take the top 10 most similar users
    4. Recommend books those users liked that the current user
       has not yet rated

    Returns:
      (list of Book objects ordered by frequency of recommendation,
       strategy_name)
    """
    from books.models import BookRating, Book

    profile = build_taste_profile(user)

    if not profile['has_ratings']:
        return [], 'no_ratings'

    user_liked = profile['liked_book_ids']

    # Find candidate similar users: anyone who liked any of the
    # same books (co-rated at least one book >= 4)
    co_raters = BookRating.objects.filter(
        book_id__in=user_liked,
        rating__gte=4
    ).exclude(
        user=user
    ).values_list('user_id', flat=True).distinct()[:200]

    if not co_raters:
        return [], 'no_similar_users'

    # Compute Jaccard similarity for each co-rater
    similarities = []
    for other_user_id in co_raters:
        other_liked = set(
            BookRating.objects.filter(
                user_id=other_user_id,
                rating__gte=4
            ).values_list('book_id', flat=True)
        )
        intersection = len(user_liked & other_liked)
        union = len(user_liked | other_liked)
        jaccard = intersection / union if union > 0 else 0.0

        if jaccard > 0:
            similarities.append((other_user_id, jaccard, other_liked))

    if not similarities:
        return [], 'no_similar_users'

    # Top 10 most similar users
    similarities.sort(key=lambda x: x[1], reverse=True)
    top_similar = similarities[:10]

    # Collect books recommended by similar users (not yet rated by current user)
    recommendation_counts = Counter()
    for _, _, other_liked in top_similar:
        for book_id in other_liked:
            if book_id not in profile['all_rated_ids']:
                recommendation_counts[book_id] += 1

    if not recommendation_counts:
        return [], 'no_new_books'

    # Order by frequency of recommendation across similar users
    top_book_ids = [
        book_id for book_id, _ in recommendation_counts.most_common(limit)
    ]

    books = Book.objects.filter(id__in=top_book_ids)
    book_map = {book.id: book for book in books}
    results = [book_map[bid] for bid in top_book_ids if bid in book_map]

    return results, 'collaborative'


# --- Strategy 3: Popularity Fallback (Cold Start) ---

def popularity_recommendations(limit: int = 20, exclude_ids: set = None) -> tuple:
    """
    Cold-start fallback using Wilson Score Lower Bound.

    Used when:
    - User has never rated anything (no taste profile)
    - Content-based and collaborative both return no results

    Returns books with >= 5 ratings ordered by Wilson Score.
    Wilson Score penalises books with few ratings even if their
    average is perfect — avoids recommending obscure high-rated books.

    Returns:
      (list of Book objects, strategy_name)
    """
    from books.models import Book

    if exclude_ids is None:
        exclude_ids = set()

    candidates = Book.objects.exclude(
        id__in=exclude_ids
    ).filter(
        rating_count__gte=5,
        quality_score__gte=0.5
    ).order_by('-average_rating', '-rating_count')[:200]

    scored = []
    for book in candidates:
        total_votes = book.upvote_count + book.downvote_count
        ws = wilson_score_lower_bound(book.upvote_count, total_votes)
        scored.append((book, ws))

    scored.sort(key=lambda x: x[1], reverse=True)
    results = [book for book, _ in scored[:limit]]

    return results, 'popularity_wilson_score'


# --- Master Orchestrator ---

def get_recommendations(user, limit: int = 20) -> tuple:
    """
    Master recommendation orchestrator with automatic fallback.

    Priority order:
    1. Content-based (requires rated books)
    2. Collaborative filtering (requires overlap with other users)
    3. Popularity cold-start (always available)

    Returns:
      (list of Book objects, strategy_name)
    """
    # Strategy 1: Content-based
    results, strategy = content_based_recommendations(user, limit=limit)
    if results:
        return results, strategy

    # Strategy 2: Collaborative
    results, strategy = collaborative_recommendations(user, limit=limit)
    if results:
        return results, strategy

    # Strategy 3: Popularity cold-start
    profile = build_taste_profile(user)
    results, strategy = popularity_recommendations(
        limit=limit,
        exclude_ids=profile['all_rated_ids']
    )
    return results, strategy

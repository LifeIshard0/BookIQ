import re
import unicodedata
from html import unescape


# ─── Step 1: Title Normalisation ────────────────────────────────────────────

def normalise_title(raw_title: str) -> str:
    """
    Strip whitespace, decode HTML entities, apply smart title case.
    Stores result in normalized_title — preserves data provenance.
    """
    if not raw_title:
        return ''
    title = unescape(raw_title)
    title = unicodedata.normalize('NFKC', title)
    title = re.sub(r'\s+', ' ', title).strip()

    small_words = {'a', 'an', 'the', 'and', 'but', 'or', 'for',
                   'nor', 'on', 'at', 'to', 'by', 'in', 'of', 'up'}
    words = title.split()
    result = []
    for i, word in enumerate(words):
        if word.isupper() and len(word) > 1:
            result.append(word)                 # preserve acronyms e.g. NASA
        elif i == 0 or word.lower() not in small_words:
            result.append(word.capitalize())
        else:
            result.append(word.lower())
    return ' '.join(result)


# ─── Step 2: Author Standardisation ─────────────────────────────────────────

def standardise_author(raw_author: str) -> str:
    """
    Converts any name format to 'Last, First' style.
    Examples:
      'F. Scott Fitzgerald'  → 'Fitzgerald, F. Scott'
      'george orwell'        → 'Orwell, George'
      'Tolkien, J.R.R.'      → 'Tolkien, J.R.R.'  (already correct)
    """
    if not raw_author:
        return ''
    author = re.sub(r'\s+', ' ', raw_author.strip())

    if ',' in author:
        parts = [p.strip().title() for p in author.split(',', 1)]
        return ', '.join(parts)

    parts = author.split()
    if len(parts) >= 2:
        last = parts[-1].capitalize()
        first = ' '.join(p.capitalize() for p in parts[:-1])
        return f"{last}, {first}"

    return author.title()


# ─── Step 3: ISBN-13 Validation ──────────────────────────────────────────────

def validate_isbn_13(isbn: str) -> bool:
    """
    Validates ISBN-13 using the official checksum algorithm.
    The 13th digit is mathematically derived from the first 12
    using alternating weights of 1 and 3.
    Returns True if valid, False otherwise.
    """
    if not isbn:
        return False
    digits = re.sub(r'[\s\-]', '', isbn)
    if not digits.isdigit() or len(digits) != 13:
        return False
    total = sum(
        int(d) * (1 if i % 2 == 0 else 3)
        for i, d in enumerate(digits[:12])
    )
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(digits[12])


# ─── Step 4: Genre Inference (Keyword Matching) ──────────────────────────────

GENRE_KEYWORDS: dict[str, list[str]] = {
    'Fantasy': [
        'magic', 'wizard', 'dragon', 'sorcerer', 'enchant', 'spell',
        'quest', 'realm', 'elf', 'dwarf', 'mythical', 'prophecy',
        'sword', 'kingdom', 'supernatural'
    ],
    'Science Fiction': [
        'space', 'alien', 'robot', 'future', 'galaxy', 'planet',
        'spacecraft', 'cyberpunk', 'dystopia', 'artificial intelligence',
        'time travel', 'colony', 'laser', 'android', 'extraterrestrial'
    ],
    'Mystery': [
        'detective', 'murder', 'crime', 'clue', 'investigation',
        'suspect', 'mystery', 'whodunit', 'forensic', 'alibi',
        'criminal', 'sleuth', 'case', 'victim', 'witness'
    ],
    'Thriller': [
        'thriller', 'suspense', 'conspiracy', 'assassin', 'espionage',
        'spy', 'chase', 'danger', 'hostage', 'kidnap', 'terror',
        'agent', 'mission', 'explosive', 'tension'
    ],
    'Romance': [
        'love', 'romance', 'passion', 'heart', 'relationship',
        'desire', 'affair', 'wedding', 'kiss', 'soulmate',
        'attraction', 'falling in love', 'heartbreak', 'devotion'
    ],
    'Horror': [
        'horror', 'fear', 'ghost', 'haunted', 'demon', 'evil',
        'terror', 'nightmare', 'supernatural', 'vampire', 'zombie',
        'curse', 'darkness', 'sinister', 'dread'
    ],
    'Biography': [
        'biography', 'memoir', 'life story', 'autobiography',
        'personal account', 'real life', 'true story', 'profile',
        'based on', 'lived', 'grew up', 'born', 'career',
        'renowned', 'famous'
    ],
    'History': [
        'history', 'historical', 'war', 'ancient', 'empire',
        'revolution', 'century', 'civilization', 'medieval',
        'chronicle', 'battle', 'dynasty', 'archaeology', 'era'
    ],
    'Science': [
        'science', 'biology', 'physics', 'chemistry', 'evolution',
        'research', 'experiment', 'laboratory', 'theory', 'discovery',
        'quantum', 'genetics', 'universe', 'astronomy', 'hypothesis'
    ],
    'Self-Help': [
        'self-help', 'motivation', 'habit', 'productivity', 'success',
        'mindset', 'goal', 'growth', 'improve', 'achieve',
        'confidence', 'wellbeing', 'mindfulness', 'positive', 'coaching'
    ],
    'Philosophy': [
        'philosophy', 'ethics', 'morality', 'existence', 'truth',
        'reason', 'consciousness', 'logic', 'metaphysics', 'virtue',
        'justice', 'reality', 'mind', 'epistemology', 'wisdom'
    ],
    'Children': [
        'children', 'kids', 'young readers', 'illustrated',
        'picture book', 'fairy tale', 'adventure', 'animals',
        'friendship', 'school', 'family', 'playful', 'colorful'
    ],
    'Technology': [
        'technology', 'software', 'programming', 'internet', 'digital',
        'computer', 'startup', 'innovation', 'engineering', 'data',
        'algorithm', 'network', 'cybersecurity', 'machine', 'code'
    ],
    'Business': [
        'business', 'entrepreneur', 'startup', 'leadership', 'strategy',
        'management', 'finance', 'investment', 'market', 'economics',
        'corporate', 'profit', 'company', 'trade', 'commerce'
    ],
    'Fiction': [
        'novel', 'story', 'narrative', 'fiction', 'character',
        'journey', 'life', 'family', 'society', 'struggle',
        'coming of age', 'redemption', 'identity', 'culture'
    ],
}


def infer_genre_by_keywords(description: str) -> tuple[str, float]:
    """
    Assigns genre by counting keyword matches in the description.
    Returns (best_genre, confidence_score).

    Confidence = matched_keywords / total_keywords_for_genre
    capped at 1.0, scaled to reflect relative dominance.

    Returns ('Unknown', 0.0) if no keywords match.
    """
    if not description or len(description.strip()) < 10:
        return ('Unknown', 0.0)

    text = description.lower()
    scores: dict[str, int] = {}

    for genre, keywords in GENRE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > 0:
            scores[genre] = count

    if not scores:
        return ('Unknown', 0.0)

    best_genre = max(scores, key=lambda g: scores[g])
    best_count = scores[best_genre]
    total_keywords = len(GENRE_KEYWORDS[best_genre])

    # Confidence: ratio of matched keywords, capped at 1.0
    raw_confidence = best_count / total_keywords
    confidence = round(min(raw_confidence, 1.0), 3)

    return (best_genre, confidence)


# ─── Step 5: Duplicate Detection ─────────────────────────────────────────────

def is_likely_duplicate(title: str, author: str, exclude_id=None) -> bool:
    """
    Detects near-duplicate books using:
    1. Exact ISBN match — enforced at DB level (unique constraint)
    2. Fuzzy Levenshtein distance via rapidfuzz on normalised title+author
    Returns True if a likely duplicate exists.
    """
    try:
        from rapidfuzz import fuzz
        from books.models import Book

        normalised = f"{normalise_title(title)} {standardise_author(author)}".lower()

        qs = Book.objects.only('id', 'normalized_title', 'normalized_author')
        if exclude_id:
            qs = qs.exclude(id=exclude_id)

        for book in qs[:500]:
            candidate = f"{book.normalized_title} {book.normalized_author}".lower()
            score = fuzz.token_sort_ratio(normalised, candidate)
            if score >= 90:
                return True
    except Exception:
        pass
    return False


# ─── Step 6: Quality Scoring ─────────────────────────────────────────────────

def compute_quality_score(
    book_data: dict,
    isbn_valid: bool,
    genre_confidence: float
) -> float:
    """
    Weighted quality formula:
      completeness (50%) + isbn_validity (30%) + genre_confidence (20%)

    Completeness = proportion of key fields that are non-empty.
    Returns float in [0.0, 1.0].
    """
    key_fields = [
        'title', 'author', 'isbn_13', 'description',
        'genre', 'published_year', 'publisher', 'page_count'
    ]
    filled = sum(
        1 for f in key_fields
        if book_data.get(f) not in (None, '', 0)
    )
    completeness = filled / len(key_fields)
    isbn_score = 1.0 if isbn_valid else 0.0
    score = (completeness * 0.5) + (isbn_score * 0.3) + (genre_confidence * 0.2)
    return round(min(max(score, 0.0), 1.0), 3)


# ─── Step 7: Flagging ────────────────────────────────────────────────────────

QUALITY_FLAG_THRESHOLD = 0.5


def should_flag(quality_score: float) -> bool:
    """Records below threshold are sent to the curator review queue."""
    return quality_score < QUALITY_FLAG_THRESHOLD


# ─── Master Pipeline ─────────────────────────────────────────────────────────

def run_cleaning_pipeline(book_data: dict, book_id=None) -> dict:
    """
    Executes all 7 cleaning steps sequentially.

    Args:
        book_data: raw book field dictionary
        book_id:   UUID of existing book (for update deduplication)

    Returns:
        Enriched dict with normalised, scored, and flagged fields.
    """
    result = dict(book_data)

    # Step 1
    result['normalized_title'] = normalise_title(result.get('title', ''))

    # Step 2
    result['normalized_author'] = standardise_author(result.get('author', ''))

    # Step 3
    isbn_valid = validate_isbn_13(result.get('isbn_13', ''))

    # Step 4 — keyword-based genre inference (no genre provided)
    if not result.get('genre') or result['genre'].strip() == '':
        inferred_genre, confidence = infer_genre_by_keywords(
            result.get('description', '')
        )
        result['genre'] = inferred_genre
        result['genre_confidence'] = confidence
    else:
        result['genre_confidence'] = 1.0   # user-supplied genre is trusted

    # Step 5 — fuzzy duplicate detection
    fuzzy_dup = is_likely_duplicate(
        result.get('title', ''),
        result.get('author', ''),
        exclude_id=book_id
    )

    # Step 6 — quality scoring
    result['quality_score'] = compute_quality_score(
        result,
        isbn_valid=isbn_valid,
        genre_confidence=result.get('genre_confidence', 0.0)
    )
    if fuzzy_dup:
        result['quality_score'] = round(
            max(result['quality_score'] - 0.2, 0.0), 3
        )

    # Step 7 — flag low-quality records
    result['is_flagged'] = should_flag(result['quality_score'])

    return result

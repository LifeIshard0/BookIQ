from types import SimpleNamespace

from django.test import SimpleTestCase

from books.services.cleaning import (
    GENRE_KEYWORDS,
    QUALITY_FLAG_THRESHOLD,
    compute_quality_score,
    infer_genre_by_keywords,
    is_likely_duplicate,
    normalise_title,
    run_cleaning_pipeline,
    should_flag,
    standardise_author,
    validate_isbn_13,
)


class CleaningPipelineTests(SimpleTestCase):
    def test_normalise_title_strips_whitespace_and_preserves_acronyms(self):
        self.assertEqual(
            normalise_title('  the   NASA and the   moon &amp; stars  '),
            'The NASA and the Moon & Stars'
        )

    def test_standardise_author_handles_all_supported_formats(self):
        self.assertEqual(standardise_author('F. Scott Fitzgerald'), 'Fitzgerald, F. Scott')
        self.assertEqual(standardise_author('Tolkien, J.R.R.'), 'Tolkien, J.R.R.')
        self.assertEqual(standardise_author('plato'), 'Plato')

    def test_validate_isbn_13_uses_checksum(self):
        self.assertTrue(validate_isbn_13('9780306406157'))
        self.assertFalse(validate_isbn_13('9780306406158'))
        self.assertFalse(validate_isbn_13('97803064061'))

    def test_genre_inference_uses_keyword_matches(self):
        genre, confidence = infer_genre_by_keywords(
            'A dragon quest through a magical realm with a wizard and sword.'
        )

        self.assertEqual(genre, 'Fantasy')
        self.assertGreater(confidence, 0.0)

    def test_duplicate_detection_penalises_quality_score(self):
        book_data = {
            'title': 'The Hobbit',
            'author': 'J R R Tolkien',
            'isbn_13': '9780306406157',
            'description': 'A fantasy adventure about a hobbit and a quest.',
            'genre': 'Fantasy',
            'published_year': 1937,
            'publisher': 'Allen & Unwin',
            'page_count': 310,
        }
        duplicate_candidates = [
            SimpleNamespace(
                id='existing-book',
                normalized_title='The Hobbit',
                normalized_author='Tolkien, J R R',
            )
        ]

        duplicate_result = run_cleaning_pipeline(
            book_data,
            duplicate_candidates=duplicate_candidates,
        )
        clean_result = run_cleaning_pipeline(book_data, duplicate_candidates=[])

        self.assertEqual(clean_result['quality_score'], 0.9)
        self.assertEqual(duplicate_result['quality_score'], 0.7)
        self.assertFalse(clean_result['is_flagged'])
        self.assertTrue(duplicate_result['is_flagged'])

    def test_compute_quality_score_uses_documented_weights(self):
        book_data = {
            'title': 'A',
            'author': 'B',
            'isbn_13': '9780000000002',
            'description': 'C',
            'genre': 'Fantasy',
            'published_year': 2000,
            'publisher': 'D',
            'page_count': 100,
        }

        score = compute_quality_score(book_data, isbn_valid=True, genre_confidence=0.5)
        self.assertEqual(score, 0.8)

    def test_genre_dictionary_has_fourteen_classes(self):
        self.assertEqual(len(GENRE_KEYWORDS), 14)

    def test_flag_threshold_is_sixty_percent(self):
        self.assertEqual(QUALITY_FLAG_THRESHOLD, 0.8)
        self.assertTrue(should_flag(0.79))
        self.assertFalse(should_flag(0.8))

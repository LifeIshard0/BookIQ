"""Serializer unit tests for BookIQ."""

from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from books.serializers import BookRatingSerializer, BookSerializer, ImportJobSerializer


class BookSerializerTests(SimpleTestCase):
	def test_book_serializer_computed_fields_handle_votes_and_creator(self):
		serializer = BookSerializer()
		book = SimpleNamespace(
			created_by=SimpleNamespace(username='curator'),
			upvote_count=3,
			downvote_count=1,
		)

		self.assertEqual(serializer.get_created_by_username(book), 'curator')
		self.assertEqual(
			serializer.get_vote_distribution(book),
			{'upvote_ratio': 0.75, 'downvote_ratio': 0.25},
		)

	def test_book_serializer_computed_fields_handle_empty_vote_distribution(self):
		serializer = BookSerializer()
		book = SimpleNamespace(created_by=None, upvote_count=0, downvote_count=0)

		self.assertIsNone(serializer.get_created_by_username(book))
		self.assertEqual(
			serializer.get_vote_distribution(book),
			{'upvote_ratio': 0.0, 'downvote_ratio': 0.0},
		)

	def test_book_serializer_validates_and_normalizes_isbn(self):
		serializer = BookSerializer(data={
			'title': 'Valid Book',
			'author': 'Author',
			'isbn_13': '978-0306406157',
			'published_year': 2001,
			'page_count': 320,
		})

		self.assertTrue(serializer.is_valid(), serializer.errors)
		self.assertEqual(serializer.validated_data['isbn_13'], '9780306406157')

	def test_book_serializer_rejects_invalid_isbn_year_and_page_count(self):
		serializer = BookSerializer(data={
			'title': 'Invalid Book',
			'author': 'Author',
			'isbn_13': 'bad-value',
			'published_year': 999,
			'page_count': 0,
		})

		self.assertFalse(serializer.is_valid())
		self.assertIn('isbn_13', serializer.errors)
		self.assertIn('published_year', serializer.errors)
		self.assertIn('page_count', serializer.errors)

	def test_book_serializer_rejects_year_outside_supported_range(self):
		serializer = BookSerializer(data={
			'title': 'Future Book',
			'author': 'Author',
			'isbn_13': '9780306406157',
			'published_year': 2200,
		})

		self.assertFalse(serializer.is_valid())
		self.assertIn('published_year', serializer.errors)


class BookRatingSerializerTests(SimpleTestCase):
	def test_book_rating_serializer_computed_fields_use_nested_objects(self):
		serializer = BookRatingSerializer()
		rating = SimpleNamespace(
			user=SimpleNamespace(username='reader'),
			book=SimpleNamespace(title='The Hobbit'),
			vote_type='upvote',
		)

		self.assertEqual(serializer.get_username(rating), 'reader')
		self.assertEqual(serializer.get_vote_type(rating), 'upvote')
		self.assertEqual(serializer.get_book_title(rating), 'The Hobbit')

	def test_book_rating_serializer_validate_rating_bounds(self):
		serializer = BookRatingSerializer()

		self.assertEqual(serializer.validate_rating(5), 5)
		with self.assertRaisesRegex(ValidationError, 'Rating must be an integer between 1 and 5.'):
			serializer.validate_rating(0)


class ImportJobSerializerTests(SimpleTestCase):
	def test_import_job_serializer_computed_fields_cover_empty_and_populated_jobs(self):
		serializer = ImportJobSerializer()
		empty_job = SimpleNamespace(total_rows=0, cleaned_count=0, duplicate_count=0, failed_count=0, created_by=None)
		active_job = SimpleNamespace(
			total_rows=10,
			cleaned_count=6,
			duplicate_count=2,
			failed_count=1,
			created_by=SimpleNamespace(username='admin'),
		)

		self.assertIsNone(serializer.get_created_by_username(empty_job))
		self.assertEqual(serializer.get_progress_percent(empty_job), 0)
		self.assertEqual(serializer.get_created_by_username(active_job), 'admin')
		self.assertEqual(serializer.get_progress_percent(active_job), 90.0)
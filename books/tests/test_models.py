"""Model helper and signal tests for BookIQ."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from books.models import (
	Book,
	BookRating,
	ImportJob,
	run_pipeline_on_book_save,
	update_book_on_rating_delete,
	update_book_on_rating_save,
)

User = get_user_model()


class BookModelTests(SimpleTestCase):
	def test_book_str_uses_title_and_author(self):
		book = Book(title='Dune', author='Frank Herbert')

		self.assertEqual(str(book), 'Dune — Frank Herbert')

	def test_update_rating_aggregates_sets_zero_values_when_no_ratings_exist(self):
		book = SimpleNamespace(save=MagicMock())
		ratings = MagicMock()
		ratings.all.return_value = ratings
		ratings.count.return_value = 0
		book.ratings = ratings

		Book.update_rating_aggregates(book)

		self.assertEqual(book.average_rating, 0.0)
		self.assertEqual(book.rating_count, 0)
		self.assertEqual(book.upvote_count, 0)
		self.assertEqual(book.downvote_count, 0)
		ratings.aggregate.assert_not_called()
		ratings.filter.assert_not_called()
		book.save.assert_called_once_with(update_fields=[
			'average_rating', 'rating_count',
			'upvote_count', 'downvote_count'
		])

	def test_update_rating_aggregates_calculates_rating_counts(self):
		book = SimpleNamespace(save=MagicMock())
		ratings = MagicMock()
		ratings.all.return_value = ratings
		ratings.count.return_value = 4
		ratings.aggregate.return_value = {'avg': 4.125, 'count': 4}
		upvotes = MagicMock()
		upvotes.count.return_value = 3
		downvotes = MagicMock()
		downvotes.count.return_value = 1
		ratings.filter.side_effect = [upvotes, downvotes]
		book.ratings = ratings

		Book.update_rating_aggregates(book)

		self.assertEqual(book.average_rating, 4.12)
		self.assertEqual(book.rating_count, 4)
		self.assertEqual(book.upvote_count, 3)
		self.assertEqual(book.downvote_count, 1)
		ratings.aggregate.assert_called_once()
		self.assertEqual(ratings.filter.call_count, 2)
		book.save.assert_called_once_with(update_fields=[
			'average_rating', 'rating_count',
			'upvote_count', 'downvote_count'
		])

	def test_book_rating_vote_type_thresholds(self):
		book = Book(title='Book', author='Author')
		user = User(username='reader')
		upvote = BookRating(
			book=book,
			user=user,
			rating=5,
		)
		neutral = BookRating(
			book=book,
			user=user,
			rating=3,
		)
		downvote = BookRating(
			book=book,
			user=user,
			rating=2,
		)

		self.assertEqual(upvote.vote_type, 'upvote')
		self.assertEqual(neutral.vote_type, 'neutral')
		self.assertEqual(downvote.vote_type, 'downvote')

	def test_book_rating_str_uses_user_title_and_score(self):
		book = Book(title='The Hobbit', author='J.R.R. Tolkien')
		user = User(username='reader')
		rating = BookRating(
			book=book,
			user=user,
			rating=4,
		)

		self.assertEqual(str(rating), "reader rated 'The Hobbit' 4/5")

	def test_import_job_str_reports_status_and_progress(self):
		job = ImportJob(status='completed', cleaned_count=12)

		self.assertIn('ImportJob', str(job))
		self.assertIn('completed', str(job))
		self.assertIn('12 cleaned', str(job))

	def test_rating_signal_callbacks_delegate_to_book_aggregate_update(self):
		book = SimpleNamespace(update_rating_aggregates=MagicMock())
		instance = SimpleNamespace(book=book)

		update_book_on_rating_save(None, instance)
		update_book_on_rating_delete(None, instance)

		self.assertEqual(book.update_rating_aggregates.call_count, 2)

	def test_pre_save_pipeline_applies_cleaned_values_and_keeps_defaults(self):
		instance = Book(
			title='Original Title',
			author='Original Author',
			genre='Existing Genre',
		)

		with patch('books.services.cleaning.run_cleaning_pipeline', return_value={
			'normalized_title': 'Clean Title',
			'quality_score': 0.77,
		}) as mock_pipeline:
			run_pipeline_on_book_save(None, instance)

		mock_pipeline.assert_called_once_with(
			{
				'title': 'Original Title',
				'author': 'Original Author',
				'isbn_13': None,
				'description': '',
				'genre': 'Existing Genre',
				'published_year': None,
				'publisher': '',
				'page_count': None,
			},
			book_id=instance.pk,
		)
		self.assertEqual(instance.genre, 'Existing Genre')
		self.assertEqual(instance.normalized_title, 'Clean Title')
		self.assertEqual(instance.normalized_author, '')
		self.assertEqual(instance.genre_confidence, 0.0)
		self.assertEqual(instance.quality_score, 0.77)
		self.assertFalse(instance.is_flagged)
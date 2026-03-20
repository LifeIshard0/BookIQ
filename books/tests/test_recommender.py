"""Book recommendation endpoint tests."""

from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from books.views import BookViewSet


class BookRecommendationTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.reader = SimpleNamespace(username='reader', role='reader', is_authenticated=True)

	def _make_serializer(self, data):
		serializer = MagicMock()
		serializer.data = data
		return serializer

	def _run_recommendations(self, request_path, results, profile_summary, **patches):
		request = self.factory.get(request_path)
		force_authenticate(request, user=self.reader)

		serializer_data = patches.pop('serializer_data', [])
		serializer = self._make_serializer(serializer_data)

		with patch('books.views.BookListSerializer', return_value=serializer):
			context_managers = []
			for target, value in patches.items():
				context_managers.append(patch(target, return_value=value))
			for manager in context_managers:
				manager.__enter__()
			try:
				response = BookViewSet.as_view({'get': 'recommendations'})(request)
			finally:
				for manager in reversed(context_managers):
					manager.__exit__(None, None, None)

		return response

	def test_automatic_waterfall_returns_content_based(self):
		recommended_books = [
			SimpleNamespace(title='Fiction One'),
			SimpleNamespace(title='Fiction Two'),
		]
		profile = {
			'liked_genres': Counter({'Fiction': 3, 'Mystery': 2}),
			'liked_authors': Counter({'Author A': 2}),
			'liked_book_ids': {1, 2, 3, 4, 5},
			'all_rated_ids': {1, 2, 3, 4, 5, 6},
			'has_ratings': True,
		}

		serializer = self._make_serializer([
			{'title': 'Fiction One'},
			{'title': 'Fiction Two'},
		])
		request = self.factory.get('/api/books/recommendations/')
		force_authenticate(request, user=self.reader)

		with patch('books.services.recommender.get_recommendations', return_value=(recommended_books, 'content_based')) as mock_get, \
			 patch('books.services.recommender.build_taste_profile', return_value=profile) as mock_profile, \
			 patch('books.views.BookListSerializer', return_value=serializer):
			response = BookViewSet.as_view({'get': 'recommendations'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['recommendation_strategy'], 'content_based')
		self.assertEqual(response.data['profile_summary']['liked_books'], 5)
		self.assertIn('Fiction', response.data['profile_summary']['top_genres'])
		self.assertEqual(response.data['results'][0]['title'], 'Fiction One')
		mock_get.assert_called_once_with(self.reader, limit=20)
		self.assertEqual(mock_profile.call_count, 1)

	def test_force_collaborative_strategy_returns_collaborative_or_fallback(self):
		recommended_books = [SimpleNamespace(title='Shared Interest Book')]
		profile = {
			'liked_genres': Counter({'Fiction': 1}),
			'liked_authors': Counter(),
			'liked_book_ids': {11},
			'all_rated_ids': {11},
			'has_ratings': True,
		}
		serializer = self._make_serializer([{'title': 'Shared Interest Book'}])
		request = self.factory.get('/api/books/recommendations/?strategy=collaborative')
		force_authenticate(request, user=self.reader)

		with patch('books.services.recommender.collaborative_recommendations', return_value=(recommended_books, 'collaborative')) as mock_collab, \
			 patch('books.services.recommender.build_taste_profile', return_value=profile), \
			 patch('books.views.BookListSerializer', return_value=serializer):
			response = BookViewSet.as_view({'get': 'recommendations'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertIn(response.data['recommendation_strategy'], {'collaborative', 'no_similar_users'})
		mock_collab.assert_called_once_with(self.reader, limit=20)
		self.assertEqual(response.data['results'][0]['title'], 'Shared Interest Book')

	def test_force_popularity_strategy_uses_wilson_score(self):
		popular_book = SimpleNamespace(title='Top Rated Book', upvote_count=250, downvote_count=12)
		profile = {
			'liked_genres': Counter({'Fiction': 1}),
			'liked_authors': Counter(),
			'liked_book_ids': {1, 2},
			'all_rated_ids': {1, 2},
			'has_ratings': True,
		}
		serializer = self._make_serializer([{'title': 'Top Rated Book'}])
		request = self.factory.get('/api/books/recommendations/?strategy=popularity')
		force_authenticate(request, user=self.reader)

		with patch('books.services.recommender.popularity_recommendations', return_value=([popular_book], 'popularity_wilson_score')) as mock_popularity, \
			 patch('books.services.recommender.build_taste_profile', return_value=profile) as mock_profile, \
			 patch('books.views.BookListSerializer', return_value=serializer):
			response = BookViewSet.as_view({'get': 'recommendations'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['recommendation_strategy'], 'popularity_wilson_score')
		self.assertEqual(response.data['results'][0]['title'], 'Top Rated Book')
		mock_popularity.assert_called_once_with(limit=20, exclude_ids={1, 2})
		self.assertEqual(mock_profile.call_count, 2)

	def test_custom_limit_is_forwarded(self):
		recommended_books = [SimpleNamespace(title=f'Book {index}') for index in range(5)]
		profile = {
			'liked_genres': Counter({'Fiction': 2}),
			'liked_authors': Counter({'Author A': 1}),
			'liked_book_ids': {1, 2, 3, 4, 5},
			'all_rated_ids': {1, 2, 3, 4, 5},
			'has_ratings': True,
		}
		serializer = self._make_serializer([{'title': f'Book {index}'} for index in range(5)])
		request = self.factory.get('/api/books/recommendations/?limit=5')
		force_authenticate(request, user=self.reader)

		with patch('books.services.recommender.get_recommendations', return_value=(recommended_books, 'content_based')) as mock_get, \
			 patch('books.services.recommender.build_taste_profile', return_value=profile), \
			 patch('books.views.BookListSerializer', return_value=serializer):
			response = BookViewSet.as_view({'get': 'recommendations'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['limit'], 5)
		self.assertEqual(len(response.data['results']), 5)
		mock_get.assert_called_once_with(self.reader, limit=5)

	def test_unauthenticated_recommendations_returns_401(self):
		request = self.factory.get('/api/books/recommendations/')
		response = BookViewSet.as_view({'get': 'recommendations'})(request)

		self.assertEqual(response.status_code, 401)

	def test_recommendations_exclude_already_rated_books(self):
		excluded_ids = {101, 102, 103, 104, 105}
		profile = {
			'liked_genres': Counter({'Fiction': 5}),
			'liked_authors': Counter({'Author A': 2}),
			'liked_book_ids': excluded_ids,
			'all_rated_ids': excluded_ids,
			'has_ratings': True,
		}
		recommended_books = [SimpleNamespace(id=201, title='New Book', upvote_count=300, downvote_count=14)]
		serializer = self._make_serializer([{'id': 201, 'title': 'New Book'}])
		request = self.factory.get('/api/books/recommendations/?strategy=popularity')
		force_authenticate(request, user=self.reader)

		with patch('books.services.recommender.popularity_recommendations', return_value=(recommended_books, 'popularity_wilson_score')) as mock_popularity, \
			 patch('books.services.recommender.build_taste_profile', return_value=profile) as mock_profile, \
			 patch('books.views.BookListSerializer', return_value=serializer):
			response = BookViewSet.as_view({'get': 'recommendations'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['results'][0]['id'], 201)
		mock_popularity.assert_called_once_with(limit=20, exclude_ids=excluded_ids)
		self.assertEqual(mock_profile.call_count, 2)
		self.assertNotIn(response.data['results'][0]['id'], excluded_ids)
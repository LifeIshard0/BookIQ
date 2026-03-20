"""Book analytics endpoint tests."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from books.views_analytics import catalogue_summary, genre_quality, genre_trends


class AnalyticsEndpointTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.admin = SimpleNamespace(username='admin', role='admin', is_authenticated=True)
		self.reader = SimpleNamespace(username='reader', role='reader', is_authenticated=True)

	def test_catalogue_summary_returns_expected_payload(self):
		summary_payload = {
			'catalogue_health': {
				'total_books': 6400,
				'flagged_books': 312,
				'flagged_pct': 4.9,
				'avg_quality_score': 0.812,
				'quality_bands': {
					'excellent (0.8-1.0)': 4100,
					'good (0.6-0.8)': 1500,
					'fair (0.4-0.6)': 650,
					'poor (0.0-0.4)': 150,
				},
			},
			'genre_distribution': [
				{'genre': 'Fiction', 'count': 2100},
				{'genre': 'Science Fiction', 'count': 900},
			],
			'rating_statistics': {
				'total_ratings': 12450,
				'avg_rating_overall': 4.12,
				'most_rated_books': [
					{'id': '1', 'title': 'Book One', 'genre': 'Fiction', 'rating_count': 540, 'average_rating': 4.6},
				],
			},
			'top_books_by_wilson_score': [
				{'id': '1', 'title': 'Book One', 'genre': 'Fiction', 'average_rating': 4.6, 'rating_count': 540, 'wilson_score': 0.9821},
			],
			'recent_additions': [
				{'id': '2', 'title': 'New Arrival', 'genre': 'Mystery', 'quality_score': 0.901, 'created_at': '2026-03-20T12:00:00Z'},
			],
			'generated_at': '2026-03-20T12:00:00Z',
		}
		request = self.factory.get('/api/analytics/summary/')
		force_authenticate(request, user=self.admin)

		with patch('books.views_analytics.get_catalogue_summary', return_value=summary_payload) as mock_summary:
			response = catalogue_summary(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data, summary_payload)
		self.assertIn('catalogue_health', response.data)
		self.assertIn('genre_distribution', response.data)
		self.assertIn('rating_statistics', response.data)
		self.assertIn('top_books_by_wilson_score', response.data)
		self.assertIn('recent_additions', response.data)
		self.assertIn('generated_at', response.data)
		self.assertEqual(response.data['catalogue_health']['total_books'], 6400)
		self.assertIsInstance(response.data['catalogue_health']['flagged_pct'], float)
		mock_summary.assert_called_once_with()

	def test_genre_trends_returns_twelve_month_window_by_default(self):
		trends_payload = [
			{'genre': 'Fiction', 'month': '2025-02', 'avg_rating': 4.4, 'rating_count': 18},
			{'genre': 'Mystery', 'month': '2025-02', 'avg_rating': 4.1, 'rating_count': 9},
		]
		request = self.factory.get('/api/analytics/genre-trends/')
		force_authenticate(request, user=self.admin)

		with patch('books.views_analytics.get_genre_trends', return_value=trends_payload) as mock_trends:
			response = genre_trends(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['months'], 12)
		self.assertEqual(response.data['total_datapoints'], 2)
		self.assertEqual(response.data['trends'], trends_payload)
		mock_trends.assert_called_once_with(months=12)

	def test_genre_trends_custom_window_uses_requested_months(self):
		trends_payload = [
			{'genre': 'Fiction', 'month': '2026-01', 'avg_rating': 4.5, 'rating_count': 6},
		]
		request = self.factory.get('/api/analytics/genre-trends/?months=3')
		force_authenticate(request, user=self.admin)

		with patch('books.views_analytics.get_genre_trends', return_value=trends_payload) as mock_trends:
			response = genre_trends(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['months'], 3)
		self.assertEqual(response.data['total_datapoints'], 1)
		self.assertEqual(response.data['trends'], trends_payload)
		mock_trends.assert_called_once_with(months=3)

	def test_genre_quality_returns_top_genres(self):
		quality_payload = [
			{'genre': 'Fiction', 'book_count': 1200, 'avg_quality_score': 0.923, 'flagged_count': 22, 'flagged_pct': 1.8},
			{'genre': 'Science Fiction', 'book_count': 740, 'avg_quality_score': 0.901, 'flagged_count': 31, 'flagged_pct': 4.2},
			{'genre': 'Mystery', 'book_count': 510, 'avg_quality_score': 0.887, 'flagged_count': 18, 'flagged_pct': 3.5},
			{'genre': 'History', 'book_count': 430, 'avg_quality_score': 0.872, 'flagged_count': 8, 'flagged_pct': 1.9},
			{'genre': 'Biography', 'book_count': 390, 'avg_quality_score': 0.861, 'flagged_count': 5, 'flagged_pct': 1.3},
		]
		request = self.factory.get('/api/analytics/genre-quality/?limit=5')
		force_authenticate(request, user=self.admin)

		with patch('books.views_analytics.get_top_genres_by_quality', return_value=quality_payload) as mock_quality:
			response = genre_quality(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['limit'], 5)
		self.assertEqual(response.data['genres'], quality_payload)
		self.assertEqual(len(response.data['genres']), 5)
		for genre_row in response.data['genres']:
			self.assertIn('book_count', genre_row)
			self.assertIn('flagged_count', genre_row)
			self.assertIn('flagged_pct', genre_row)
		mock_quality.assert_called_once_with(limit=5)

	def test_summary_blocks_non_admin_users_with_403(self):
		request = self.factory.get('/api/analytics/summary/')
		force_authenticate(request, user=self.reader)

		response = catalogue_summary(request)

		self.assertEqual(response.status_code, 403)

	def test_summary_blocks_unauthenticated_users_with_401(self):
		request = self.factory.get('/api/analytics/summary/')

		response = catalogue_summary(request)

		self.assertEqual(response.status_code, 401)
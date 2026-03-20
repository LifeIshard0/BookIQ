"""Direct view helper tests for BookIQ viewsets and analytics endpoints."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from books.views import BookViewSet, ImportJobViewSet, RatingViewSet
from books.views_analytics import catalogue_summary, genre_quality, genre_trends


class BookViewHelperTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.view = BookViewSet()

	def test_get_queryset_filters_flagged_books_for_true_and_false_values(self):
		base_queryset = MagicMock()
		base_queryset.all.return_value = base_queryset
		base_queryset.filter.return_value = base_queryset
		self.view.queryset = base_queryset

		self.view.request = SimpleNamespace(query_params={'is_flagged': 'true'})
		result = self.view.get_queryset()
		self.assertIs(result, base_queryset)
		base_queryset.filter.assert_called_with(is_flagged=True)

		base_queryset.filter.reset_mock()
		self.view.request = SimpleNamespace(query_params={'is_flagged': ' no '})
		result = self.view.get_queryset()
		self.assertIs(result, base_queryset)
		base_queryset.filter.assert_called_with(is_flagged=False)

	def test_get_queryset_ignores_unrecognized_flag_filter_values(self):
		base_queryset = MagicMock()
		base_queryset.all.return_value = base_queryset
		self.view.queryset = base_queryset
		self.view.request = SimpleNamespace(query_params={'is_flagged': 'maybe'})

		result = self.view.get_queryset()

		self.assertIs(result, base_queryset)
		base_queryset.filter.assert_not_called()

	def test_get_serializer_class_and_permissions_cover_all_actions(self):
		self.view.action = 'list'
		self.assertIs(self.view.get_serializer_class(), self.view.get_serializer_class())
		self.assertIs(self.view.get_serializer_class(), BookViewSet.get_serializer_class(self.view))

		self.view.action = 'create'
		self.assertEqual(type(self.view.get_permissions()[0]).__name__, 'IsCuratorOrAbove')
		self.view.action = 'destroy'
		self.assertEqual(type(self.view.get_permissions()[0]).__name__, 'IsAdminRole')
		self.view.action = 'recommendations'
		self.assertEqual(type(self.view.get_permissions()[0]).__name__, 'IsReaderOrAbove')
		self.view.action = 'custom'
		self.assertEqual(type(self.view.get_permissions()[0]).__name__, 'IsAuthenticatedOrReadOnly')


class ImportAndRatingViewHelperTests(SimpleTestCase):
	def test_import_job_queryset_respects_swagger_fake_view_and_user_filter(self):
		view = ImportJobViewSet()
		fake_none = MagicMock()
		fake_none.none.return_value = fake_none
		manager = MagicMock()
		manager.none.return_value = fake_none
		manager.filter.return_value.order_by.return_value = ['job']

		with patch('books.views.ImportJob', SimpleNamespace(objects=manager)):
			view.swagger_fake_view = True
			self.assertIs(view.get_queryset(), fake_none)

			view.swagger_fake_view = False
			view.request = SimpleNamespace(user=SimpleNamespace(username='admin'))
			self.assertEqual(view.get_queryset(), ['job'])
			manager.filter.assert_called_with(created_by=view.request.user)

	def test_rating_queryset_respects_swagger_fake_view_and_user_filter(self):
		view = RatingViewSet()
		fake_none = MagicMock()
		fake_none.none.return_value = fake_none
		manager = MagicMock()
		manager.none.return_value = fake_none
		manager.filter.return_value.select_related.return_value.order_by.return_value = ['rating']

		with patch('books.views.BookRating', SimpleNamespace(objects=manager)):
			view.swagger_fake_view = True
			self.assertIs(view.get_queryset(), fake_none)

			view.swagger_fake_view = False
			view.request = SimpleNamespace(user=SimpleNamespace(username='reader'))
			self.assertEqual(view.get_queryset(), ['rating'])
			manager.filter.assert_called_with(user=view.request.user)


class AnalyticsViewHelperTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.admin = SimpleNamespace(username='admin', role='admin', is_authenticated=True)

	def test_genre_trends_defaults_invalid_months_to_twelve(self):
		request = self.factory.get('/api/analytics/genre-trends/?months=bad')
		force_authenticate(request, user=self.admin)
		with patch('books.views_analytics.get_genre_trends', return_value=[{'genre': 'Fiction'}]) as mock_trends:
			response = genre_trends(request)

		self.assertEqual(response.data['months'], 12)
		mock_trends.assert_called_once_with(months=12)

	def test_genre_quality_defaults_invalid_limit_to_ten(self):
		request = self.factory.get('/api/analytics/genre-quality/?limit=bad')
		force_authenticate(request, user=self.admin)
		with patch('books.views_analytics.get_top_genres_by_quality', return_value=[{'genre': 'Fiction'}]) as mock_quality:
			response = genre_quality(request)

		self.assertEqual(response.data['limit'], 10)
		mock_quality.assert_called_once_with(limit=10)

	def test_catalogue_summary_returns_service_payload(self):
		request = self.factory.get('/api/analytics/summary/')
		force_authenticate(request, user=self.admin)
		payload = {'catalogue_health': {'total_books': 1}}
		with patch('books.views_analytics.get_catalogue_summary', return_value=payload) as mock_summary:
			response = catalogue_summary(request)

		self.assertEqual(response.data, payload)
		mock_summary.assert_called_once_with()
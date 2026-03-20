"""Book search and pagination endpoint tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from books.views import BookViewSet


class SearchQuerySet(list):
	def all(self):
		return self

	def filter(self, **kwargs):
		result = self
		for key, value in kwargs.items():
			result = [item for item in result if getattr(item, key) == value]
		return SearchQuerySet(result)

	def order_by(self, field_name):
		reverse = field_name.startswith('-')
		attr_name = field_name.lstrip('-')
		return SearchQuerySet(
			sorted(self, key=lambda item: getattr(item, attr_name), reverse=reverse)
		)


class BookSearchTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.reader = SimpleNamespace(username='reader', role='reader', is_authenticated=True)
		self.curator = SimpleNamespace(username='curator', role='curator', is_authenticated=True)
		self.admin = SimpleNamespace(username='admin', role='admin', is_authenticated=True)

	def _make_paginator(self, response_data, page):
		paginator = MagicMock()
		paginator.paginate_queryset.return_value = page
		paginator.get_paginated_response.return_value = Response(response_data)
		return paginator

	def _make_filterset(self, queryset):
		filterset = MagicMock()
		filterset.is_valid.return_value = True
		filterset.qs = queryset
		return filterset

	def test_basic_keyword_search_returns_paginated_results(self):
		request = self.factory.get('/api/books/search/?q=gatsby')

		books = SearchQuerySet([
			SimpleNamespace(
				title='The Great Gatsby',
				author='F. Scott Fitzgerald',
				genre='Fiction',
				is_flagged=False,
				quality_score=0.91,
				average_rating=3.91,
				rating_count=182,
			),
		])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = [{'title': 'The Great Gatsby'}]
		paginator = self._make_paginator(
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': serializer.data,
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['query'], 'gatsby')
		self.assertEqual(response.data['results'][0]['title'], 'The Great Gatsby')

	def test_genre_filter_returns_matching_books(self):
		request = self.factory.get('/api/books/search/?genre=fiction')
		books = SearchQuerySet([
			SimpleNamespace(title='Novel One', genre='Fiction', quality_score=0.9, average_rating=4.1, rating_count=10),
		])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = [{'title': 'Novel One', 'genre': 'Fiction'}]
		paginator = self._make_paginator(
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': serializer.data,
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['filters_applied'], {'genre': 'fiction'})

	def test_combined_keyword_and_quality_filter_returns_matches(self):
		request = self.factory.get('/api/books/search/?q=war&min_quality=0.7')
		books = SearchQuerySet([
			SimpleNamespace(title='War and Peace', quality_score=0.9, average_rating=4.6, rating_count=54),
		])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = [{'title': 'War and Peace', 'quality_score': 0.9}]
		paginator = self._make_paginator(
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': serializer.data,
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['filters_applied'], {'q': 'war', 'min_quality': '0.7'})

	def test_flagged_books_require_curator_or_admin(self):
		request = self.factory.get('/api/books/search/?is_flagged=true')
		force_authenticate(request, user=self.reader)

		response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 403)

	def test_curator_can_search_flagged_books(self):
		request = self.factory.get('/api/books/search/?is_flagged=true')
		force_authenticate(request, user=self.curator)

		books = SearchQuerySet([
			SimpleNamespace(title='Flagged Book', is_flagged=True, rating_count=5, quality_score=0.8, average_rating=4.2),
		])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = [{'title': 'Flagged Book', 'is_flagged': True}]
		paginator = self._make_paginator(
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': serializer.data,
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['results'][0]['title'], 'Flagged Book')

	def test_publication_year_range_filters_books(self):
		request = self.factory.get('/api/books/search/?published_after=2000&published_before=2010')
		books = SearchQuerySet([
			SimpleNamespace(title='Mid-2000s Book', published_year=2005, rating_count=7, quality_score=0.76, average_rating=3.8),
		])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = [{'title': 'Mid-2000s Book', 'published_year': 2005}]
		paginator = self._make_paginator(
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': serializer.data,
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['filters_applied'], {'published_after': '2000', 'published_before': '2010'})

	def test_high_rated_books_order_by_rating_count(self):
		request = self.factory.get('/api/books/search/?min_rating=4.0&ordering=-rating_count')
		books = SearchQuerySet([
			SimpleNamespace(title='Most Rated', average_rating=4.8, rating_count=500, quality_score=0.95),
			SimpleNamespace(title='Less Rated', average_rating=4.2, rating_count=120, quality_score=0.92),
		])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = [
			{'title': 'Most Rated', 'rating_count': 500},
			{'title': 'Less Rated', 'rating_count': 120},
		]
		paginator = self._make_paginator(
			{
				'count': 2,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': serializer.data,
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item['title'] for item in response.data['results']], ['Most Rated', 'Less Rated'])

	def test_search_pagination_returns_page_metadata(self):
		request = self.factory.get('/api/books/search/?q=the&page=2&page_size=5')
		books = SearchQuerySet([
			SimpleNamespace(title=f'Book {index}', rating_count=index, quality_score=0.8, average_rating=4.0)
			for index in range(5)
		])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = [{'title': f'Book {index}'} for index in range(5)]
		paginator = self._make_paginator(
			{
				'count': 10,
				'total_pages': 2,
				'current_page': 2,
				'next': None,
				'previous': 'http://testserver/api/books/search/?q=the&page=1&page_size=5',
				'results': serializer.data,
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['current_page'], 2)
		self.assertEqual(response.data['total_pages'], 2)
		self.assertEqual(response.data['count'], 10)
		self.assertEqual(len(response.data['results']), 5)

	def test_empty_search_returns_empty_paginated_result(self):
		request = self.factory.get('/api/books/search/?q=xyzzy123notabook')
		books = SearchQuerySet([])
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = []
		paginator = self._make_paginator(
			{
				'count': 0,
				'total_pages': 0,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [],
			},
			page=books,
		)

		with patch('books.views.BookFilter', return_value=filterset), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'search'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['count'], 0)
		self.assertEqual(response.data['results'], [])

	def test_list_endpoint_is_paginated(self):
		request = self.factory.get(reverse('book-list'))
		books = SearchQuerySet([
			SimpleNamespace(title='Book One', rating_count=10, quality_score=0.81, created_at=1),
			SimpleNamespace(title='Book Two', rating_count=8, quality_score=0.79, created_at=2),
		])
		serializer = MagicMock()
		serializer.data = [{'title': 'Book One'}, {'title': 'Book Two'}]
		paginator = self._make_paginator(
			{
				'count': 2,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': serializer.data,
			},
			page=books,
		)

		with patch.object(BookViewSet, 'get_queryset', return_value=books), \
			 patch.object(BookViewSet, 'filter_queryset', return_value=books), \
			 patch('books.views.BookListSerializer', return_value=serializer), \
			 patch('books.views.BookPagination', return_value=paginator):
			response = BookViewSet.as_view({'get': 'list'})(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['count'], 2)
		self.assertEqual(response.data['results'][0]['title'], 'Book One')
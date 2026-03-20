"""Book search and pagination endpoint tests."""

from contextlib import ExitStack
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

	def none(self):
		return SearchQuerySet([])

	def filter(self, **kwargs):
		result = self
		for key, value in kwargs.items():
			if key == 'search_vector':
				continue
			if key == 'rank__gte':
				result = [item for item in result if getattr(item, 'rank', value) >= value]
				continue
			result = [item for item in result if getattr(item, key) == value]
		return SearchQuerySet(result)

	def annotate(self, **kwargs):
		return self

	def order_by(self, field_name):
		reverse = field_name.startswith('-')
		attr_name = field_name.lstrip('-')
		return SearchQuerySet(
			sorted(self, key=lambda item: getattr(item, attr_name, 0), reverse=reverse)
		)

	def distinct(self):
		return self


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

	def _run_search(self, request_path, books, serializer_data, paginator_data, full_text_search_return=None):
		request = self.factory.get(request_path)
		filterset = self._make_filterset(books)
		serializer = MagicMock()
		serializer.data = serializer_data
		paginator = self._make_paginator(paginator_data, page=books)

		with ExitStack() as stack:
			stack.enter_context(patch('books.views.BookFilter', return_value=filterset))
			stack.enter_context(patch('books.views.BookListSerializer', return_value=serializer))
			stack.enter_context(patch('books.views.BookPagination', return_value=paginator))
			search_mock = None
			if full_text_search_return is not None:
				search_mock = stack.enter_context(
					patch('books.services.search.full_text_search', return_value=full_text_search_return)
				)
			response = BookViewSet.as_view({'get': 'search'})(request)

		return response, search_mock

	def _run_hybrid_search(
		self,
		request_path,
		books,
		service_result,
		serializer_data_by_title,
		wilson_score_value=0.4219,
	):
		request = self.factory.get(request_path)
		filterset = self._make_filterset(books)

		def serializer_side_effect(book):
			serializer = MagicMock()
			serializer.data = serializer_data_by_title[book.title]
			return serializer

		with ExitStack() as stack:
			stack.enter_context(patch('books.views.BookFilter', return_value=filterset))
			stack.enter_context(patch('books.views.BookListSerializer', side_effect=serializer_side_effect))
			stack.enter_context(patch('books.services.search.hybrid_search', return_value=service_result))
			stack.enter_context(patch('books.views.wilson_score_lower_bound', return_value=wilson_score_value))
			response = BookViewSet.as_view({'get': 'hybrid_search'})(request)

		return response

	def test_basic_fts_query_returns_rank_and_headline(self):
		books = SearchQuerySet([
			SimpleNamespace(
				title='1984',
				author='George Orwell',
				genre='Dystopian',
				quality_score=0.96,
				average_rating=4.2,
				rating_count=2400,
				rank=0.94231,
				headline='A <mark>dystopian</mark> <mark>society</mark> shaped by surveillance.',
			),
		])
		response, search_mock = self._run_search(
			'/api/books/search/?q=dystopian+society',
			books,
			[{'title': '1984'}],
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [{'title': '1984'}],
			},
			full_text_search_return=books,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['query'], 'dystopian society')
		self.assertEqual(response.data['search_type'], 'full_text_search')
		self.assertEqual(response.data['results'][0]['title'], '1984')
		self.assertEqual(response.data['results'][0]['rank'], 0.9423)
		self.assertIn('<mark>', response.data['results'][0]['headline'])
		search_mock.assert_called_once_with('dystopian society', queryset=books)

	def test_phrase_search_uses_websearch_syntax(self):
		books = SearchQuerySet([
			SimpleNamespace(
				title='The Great Gatsby',
				author='F. Scott Fitzgerald',
				genre='Classic',
				quality_score=0.93,
				average_rating=4.4,
				rating_count=3200,
				rank=0.9912,
				headline='An exact <mark>Great Gatsby</mark> phrase match.',
			),
			SimpleNamespace(
				title='Gatsby and Friends',
				author='Another Author',
				genre='Classic',
				quality_score=0.81,
				average_rating=3.9,
				rating_count=140,
				rank=0.2145,
				headline='A weaker partial match.',
			),
		])
		response, search_mock = self._run_search(
			'/api/books/search/?q=%22great+gatsby%22',
			books,
			[
				{'title': 'The Great Gatsby'},
				{'title': 'Gatsby and Friends'},
			],
			{
				'count': 2,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [
					{'title': 'The Great Gatsby'},
					{'title': 'Gatsby and Friends'},
				],
			},
			full_text_search_return=books,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['results'][0]['title'], 'The Great Gatsby')
		self.assertEqual(search_mock.call_args.args[0], '"great gatsby"')

	def test_or_query_returns_books_for_both_authors(self):
		books = SearchQuerySet([
			SimpleNamespace(
				title='The Hobbit',
				author='J.R.R. Tolkien',
				genre='Fantasy',
				quality_score=0.95,
				average_rating=4.8,
				rating_count=5000,
				rank=0.9611,
				headline='Middle-earth adventure.',
			),
			SimpleNamespace(
				title='Harry Potter and the Philosopher\'s Stone',
				author='J.K. Rowling',
				genre='Fantasy',
				quality_score=0.94,
				average_rating=4.7,
				rating_count=4200,
				rank=0.9453,
				headline='Wizarding world adventure.',
			),
		])
		response, search_mock = self._run_search(
			'/api/books/search/?q=tolkien+OR+rowling',
			books,
			[
				{'title': 'The Hobbit', 'author': 'J.R.R. Tolkien'},
				{'title': 'Harry Potter and the Philosopher\'s Stone', 'author': 'J.K. Rowling'},
			],
			{
				'count': 2,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [
					{'title': 'The Hobbit', 'author': 'J.R.R. Tolkien'},
					{'title': 'Harry Potter and the Philosopher\'s Stone', 'author': 'J.K. Rowling'},
				],
			},
			full_text_search_return=books,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item['author'] for item in response.data['results']], ['J.R.R. Tolkien', 'J.K. Rowling'])
		search_mock.assert_called_once_with('tolkien OR rowling', queryset=books)

	def test_exclusion_query_filters_out_banned_terms(self):
		books = SearchQuerySet([
			SimpleNamespace(
				title='Magic Without Wizards',
				author='Author One',
				genre='Fantasy',
				quality_score=0.88,
				average_rating=4.1,
				rating_count=320,
				rank=0.8732,
				headline='A magic story with no wizard in sight.',
			),
		])
		response, search_mock = self._run_search(
			'/api/books/search/?q=magic+-wizard',
			books,
			[{'title': 'Magic Without Wizards'}],
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [{'title': 'Magic Without Wizards'}],
			},
			full_text_search_return=books,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['results'][0]['title'], 'Magic Without Wizards')
		search_mock.assert_called_once_with('magic -wizard', queryset=books)

	def test_fts_with_genre_filter_applies_both_constraints(self):
		books = SearchQuerySet([
			SimpleNamespace(
				title='Space Atlas',
				author='Writer One',
				genre='Science Fiction',
				quality_score=0.84,
				average_rating=4.3,
				rating_count=110,
				rank=0.9024,
				headline='A journey through <mark>space</mark>.',
			),
		])
		response, search_mock = self._run_search(
			'/api/books/search/?q=space&genre=science+fiction',
			books,
			[{'title': 'Space Atlas', 'genre': 'Science Fiction'}],
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [{'title': 'Space Atlas', 'genre': 'Science Fiction'}],
			},
			full_text_search_return=books,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['search_type'], 'full_text_search')
		self.assertEqual(response.data['filters_applied'], {'genre': 'science fiction'})
		self.assertEqual(response.data['results'][0]['genre'], 'Science Fiction')
		search_mock.assert_called_once_with('space', queryset=books)

	def test_fts_with_quality_filter_keeps_high_quality_results(self):
		books = SearchQuerySet([
			SimpleNamespace(
				title='A History of Europe',
				author='Historian',
				genre='History',
				quality_score=0.83,
				average_rating=4.5,
				rating_count=480,
				rank=0.9176,
				headline='A broad <mark>history</mark> survey.',
			),
		])
		response, search_mock = self._run_search(
			'/api/books/search/?q=history&min_quality=0.7',
			books,
			[{'title': 'A History of Europe', 'quality_score': 0.83}],
			{
				'count': 1,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [{'title': 'A History of Europe', 'quality_score': 0.83}],
			},
			full_text_search_return=books,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['filters_applied'], {'min_quality': '0.7'})
		self.assertGreaterEqual(response.data['results'][0]['quality_score'], 0.7)
		search_mock.assert_called_once_with('history', queryset=books)

	def test_filter_only_query_orders_by_average_rating(self):
		response, search_mock = self._run_search(
			'/api/books/search/?genre=biography&min_rating=4.0',
			SearchQuerySet([
				SimpleNamespace(
					title='Biography B',
					genre='Biography',
					quality_score=0.81,
					average_rating=4.1,
					rating_count=60,
				),
				SimpleNamespace(
					title='Biography A',
					genre='Biography',
					quality_score=0.88,
					average_rating=4.7,
					rating_count=120,
				),
			]),
			[
				{'title': 'Biography A', 'average_rating': 4.7},
				{'title': 'Biography B', 'average_rating': 4.1},
			],
			{
				'count': 2,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [
					{'title': 'Biography A', 'average_rating': 4.7},
					{'title': 'Biography B', 'average_rating': 4.1},
				],
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['search_type'], 'filter_only')
		self.assertEqual([item['title'] for item in response.data['results']], ['Biography A', 'Biography B'])
		self.assertNotIn('rank', response.data['results'][0])
		self.assertNotIn('headline', response.data['results'][0])
		self.assertIsNone(search_mock)

	def test_stemming_query_returns_run_variants(self):
		books = SearchQuerySet([
			SimpleNamespace(
				title='The Runner',
				author='Writer One',
				genre='Fiction',
				quality_score=0.86,
				average_rating=4.0,
				rating_count=84,
				rank=0.9321,
				headline='A tale about a <mark>runner</mark>.',
			),
			SimpleNamespace(
				title='Long Runs',
				author='Writer Two',
				genre='Fiction',
				quality_score=0.82,
				average_rating=3.9,
				rating_count=51,
				rank=0.8814,
				headline='Stories about <mark>runs</mark> and endurance.',
			),
			SimpleNamespace(
				title='Run Fast',
				author='Writer Three',
				genre='Fiction',
				quality_score=0.8,
				average_rating=3.8,
				rating_count=40,
				rank=0.8025,
				headline='A book about a <mark>run</mark>.',
			),
		])
		response, search_mock = self._run_search(
			'/api/books/search/?q=running',
			books,
			[
				{'title': 'The Runner'},
				{'title': 'Long Runs'},
				{'title': 'Run Fast'},
			],
			{
				'count': 3,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [
					{'title': 'The Runner'},
					{'title': 'Long Runs'},
					{'title': 'Run Fast'},
				],
			},
			full_text_search_return=books,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['results'][0]['title'], 'The Runner')
		self.assertEqual({item['title'] for item in response.data['results']}, {'The Runner', 'Long Runs', 'Run Fast'})
		search_mock.assert_called_once_with('running', queryset=books)

	def test_empty_query_returns_all_books_ordered_by_average_rating(self):
		response, search_mock = self._run_search(
			'/api/books/search/?genre=biography&min_rating=4.0',
			SearchQuerySet([
				SimpleNamespace(
					title='Biography B',
					genre='Biography',
					quality_score=0.81,
					average_rating=4.1,
					rating_count=60,
				),
				SimpleNamespace(
					title='Biography A',
					genre='Biography',
					quality_score=0.88,
					average_rating=4.7,
					rating_count=120,
				),
			]),
			[
				{'title': 'Biography A', 'average_rating': 4.7},
				{'title': 'Biography B', 'average_rating': 4.1},
			],
			{
				'count': 2,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [
					{'title': 'Biography A', 'average_rating': 4.7},
					{'title': 'Biography B', 'average_rating': 4.1},
				],
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['query'], '')
		self.assertEqual(response.data['search_type'], 'filter_only')
		self.assertEqual([item['title'] for item in response.data['results']], ['Biography A', 'Biography B'])
		self.assertNotIn('rank', response.data['results'][0])
		self.assertNotIn('headline', response.data['results'][0])
		self.assertIsNone(search_mock)

	def test_basic_hybrid_search_returns_rrf_scores(self):
		popular_book = SimpleNamespace(
			title='War and Peace',
			author='Leo Tolstoy',
			genre='Historical Fiction',
			quality_score=0.97,
			average_rating=4.7,
			rating_count=1800,
			upvote_count=400,
			downvote_count=40,
			rank=0.8821,
		)
		query_result = {
			'results': [(popular_book, 0.0278)],
			'count': 1,
			'page': 1,
			'page_size': 20,
			'total_pages': 1,
			'query': 'war',
			'fts_weight': 0.7,
			'popularity_weight': 0.3,
		}
		response = self._run_hybrid_search(
			'/api/books/hybrid-search/?q=war',
			SearchQuerySet([popular_book]),
			query_result,
			{
				'War and Peace': {'title': 'War and Peace', 'average_rating': 4.7},
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['search_type'], 'hybrid_rrf')
		self.assertEqual(response.data['query'], 'war')
		self.assertEqual(response.data['count'], 1)
		self.assertEqual(response.data['page'], 1)
		self.assertEqual(response.data['page_size'], 20)
		self.assertEqual(response.data['total_pages'], 1)
		self.assertEqual(response.data['fts_weight'], 0.7)
		self.assertEqual(response.data['popularity_weight'], 0.3)
		self.assertEqual(response.data['results'][0]['rrf_score'], 0.0278)
		self.assertEqual(response.data['results'][0]['wilson_score'], 0.4219)
		self.assertEqual(response.data['results'][0]['fts_rank'], 0.8821)

	def test_hybrid_vs_fts_ordering_differs_for_same_query(self):
		fts_books = SearchQuerySet([
			SimpleNamespace(title='Exact History Match', rank=0.9921, headline='Exact match.', upvote_count=12, downvote_count=3),
			SimpleNamespace(title='Well Rated History Book', rank=0.7312, headline='Popular history.', upvote_count=120, downvote_count=10),
		])
		fts_response, _ = self._run_search(
			'/api/books/search/?q=history',
			fts_books,
			[{'title': 'Exact History Match'}, {'title': 'Well Rated History Book'}],
			{
				'count': 2,
				'total_pages': 1,
				'current_page': 1,
				'next': None,
				'previous': None,
				'results': [{'title': 'Exact History Match'}, {'title': 'Well Rated History Book'}],
			},
			full_text_search_return=fts_books,
		)

		hybrid_books = SearchQuerySet([
			SimpleNamespace(title='Exact History Match', rank=0.9921, upvote_count=12, downvote_count=3),
			SimpleNamespace(title='Well Rated History Book', rank=0.7312, upvote_count=120, downvote_count=10),
		])
		hybrid_response = self._run_hybrid_search(
			'/api/books/hybrid-search/?q=history',
			hybrid_books,
			{
				'results': [
					(hybrid_books[1], 0.0301),
					(hybrid_books[0], 0.0298),
				],
				'count': 2,
				'page': 1,
				'page_size': 20,
				'total_pages': 1,
				'query': 'history',
				'fts_weight': 0.7,
				'popularity_weight': 0.3,
			},
			{
				'Exact History Match': {'title': 'Exact History Match'},
				'Well Rated History Book': {'title': 'Well Rated History Book'},
			},
		)

		self.assertEqual([item['title'] for item in fts_response.data['results']], ['Exact History Match', 'Well Rated History Book'])
		self.assertEqual([item['title'] for item in hybrid_response.data['results']], ['Well Rated History Book', 'Exact History Match'])
		self.assertNotEqual(
			[item['title'] for item in fts_response.data['results']],
			[item['title'] for item in hybrid_response.data['results']]
		)

	def test_hybrid_popularity_weight_is_forwarded(self):
		books = SearchQuerySet([
			SimpleNamespace(title='Popular Science', rank=0.8123, upvote_count=220, downvote_count=18),
			SimpleNamespace(title='Obscure Science', rank=0.9932, upvote_count=3, downvote_count=1),
		])
		response = self._run_hybrid_search(
			'/api/books/hybrid-search/?q=science&fts_weight=0.3&popularity_weight=0.7',
			books,
			{
				'results': [(books[0], 0.0312), (books[1], 0.0308)],
				'count': 2,
				'page': 1,
				'page_size': 20,
				'total_pages': 1,
				'query': 'science',
				'fts_weight': 0.3,
				'popularity_weight': 0.7,
			},
			{
				'Popular Science': {'title': 'Popular Science'},
				'Obscure Science': {'title': 'Obscure Science'},
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['fts_weight'], 0.3)
		self.assertEqual(response.data['popularity_weight'], 0.7)
		self.assertEqual(response.data['results'][0]['title'], 'Popular Science')

	def test_hybrid_pure_relevance_weights_are_forwarded(self):
		books = SearchQuerySet([
			SimpleNamespace(title='Science Primer', rank=0.9955, upvote_count=5, downvote_count=1),
			SimpleNamespace(title='Science Anthology', rank=0.7821, upvote_count=140, downvote_count=10),
		])
		response = self._run_hybrid_search(
			'/api/books/hybrid-search/?q=science&fts_weight=1.0&popularity_weight=0.0',
			books,
			{
				'results': [(books[0], 0.0320), (books[1], 0.0302)],
				'count': 2,
				'page': 1,
				'page_size': 20,
				'total_pages': 1,
				'query': 'science',
				'fts_weight': 1.0,
				'popularity_weight': 0.0,
			},
			{
				'Science Primer': {'title': 'Science Primer'},
				'Science Anthology': {'title': 'Science Anthology'},
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['search_type'], 'hybrid_rrf')
		self.assertEqual(response.data['fts_weight'], 1.0)
		self.assertEqual(response.data['popularity_weight'], 0.0)
		self.assertEqual([item['title'] for item in response.data['results']], ['Science Primer', 'Science Anthology'])

	def test_hybrid_genre_filter_applies_and_returns_hybrid_results(self):
		books = SearchQuerySet([
			SimpleNamespace(title='Mystery Detective', genre='Mystery', rank=0.9222, upvote_count=80, downvote_count=12),
		])
		response = self._run_hybrid_search(
			'/api/books/hybrid-search/?q=detective&genre=mystery',
			books,
			{
				'results': [(books[0], 0.0297)],
				'count': 1,
				'page': 1,
				'page_size': 20,
				'total_pages': 1,
				'query': 'detective',
				'fts_weight': 0.7,
				'popularity_weight': 0.3,
			},
			{
				'Mystery Detective': {'title': 'Mystery Detective', 'genre': 'Mystery'},
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['search_type'], 'hybrid_rrf')
		self.assertEqual(response.data['results'][0]['genre'], 'Mystery')

	def test_hybrid_missing_query_returns_400(self):
		request = self.factory.get('/api/books/hybrid-search/')
		response = BookViewSet.as_view({'get': 'hybrid_search'})(request)

		self.assertEqual(response.status_code, 400)
		self.assertIn('required', response.data['detail'])

	def test_hybrid_invalid_weight_returns_400(self):
		request = self.factory.get('/api/books/hybrid-search/?q=fiction&fts_weight=5.0')
		response = BookViewSet.as_view({'get': 'hybrid_search'})(request)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(
			response.data['detail'],
			'fts_weight and popularity_weight must be floats between 0.0 and 1.0.'
		)

	def test_hybrid_pagination_returns_requested_page(self):
		books = SearchQuerySet([
			SimpleNamespace(title=f'Love Book {index}', rank=0.9 - (index * 0.01), upvote_count=50 + index, downvote_count=5)
			for index in range(5)
		])
		response = self._run_hybrid_search(
			'/api/books/hybrid-search/?q=love&page=2&page_size=5',
			books,
			{
				'results': [(book, round(0.03 - (index * 0.001), 4)) for index, book in enumerate(books)],
				'count': 10,
				'page': 2,
				'page_size': 5,
				'total_pages': 2,
				'query': 'love',
				'fts_weight': 0.7,
				'popularity_weight': 0.3,
			},
			{book.title: {'title': book.title} for book in books},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['page'], 2)
		self.assertEqual(response.data['page_size'], 5)
		self.assertEqual(response.data['total_pages'], 2)
		self.assertEqual(len(response.data['results']), 5)

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
		self.assertEqual(response.data['search_type'], 'full_text_search')
		self.assertEqual(response.data['filters_applied'], {'min_quality': '0.7'})
		self.assertEqual(response.data['results'][0]['title'], 'War and Peace')

	def test_reader_can_search_flagged_books(self):
		request = self.factory.get('/api/books/search/?is_flagged=true')
		force_authenticate(request, user=self.reader)

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
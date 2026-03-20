"""Focused unit tests for analytics, search, and recommender services."""

from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from books.services.analytics import (
	get_catalogue_summary,
	get_genre_trends,
	get_top_genres_by_quality,
)
from books.services.recommender import (
	build_taste_profile,
	collaborative_recommendations,
	content_based_recommendations,
	get_recommendations,
	popularity_recommendations,
)
from books.services.search import (
	build_search_query,
	full_text_search,
	hybrid_search,
	reciprocal_rank_fusion,
	rebuild_all_search_vectors,
	rebuild_search_vector,
	wilson_score_lower_bound,
)


class FakeQuerySet:
	def __init__(self, rows=None, count_value=None, aggregate_value=None):
		self.rows = list(rows or [])
		self.count_value = count_value
		self.aggregate_value = aggregate_value or {}
		self.calls = []
		self.updated = None

	def filter(self, **kwargs):
		self.calls.append(('filter', kwargs))
		return self

	def exclude(self, **kwargs):
		self.calls.append(('exclude', kwargs))
		return self

	def annotate(self, **kwargs):
		self.calls.append(('annotate', kwargs))
		return self

	def values(self, *args):
		self.calls.append(('values', args))
		return self

	def values_list(self, *args, **kwargs):
		self.calls.append(('values_list', args, kwargs))
		return self

	def select_related(self, *args):
		self.calls.append(('select_related', args))
		return self

	def distinct(self):
		self.calls.append(('distinct', ()))
		return self

	def order_by(self, *args):
		self.calls.append(('order_by', args))
		return self

	def count(self):
		return self.count_value if self.count_value is not None else len(self.rows)

	def aggregate(self, **kwargs):
		self.calls.append(('aggregate', kwargs))
		return self.aggregate_value

	def update(self, **kwargs):
		self.updated = kwargs
		return len(self.rows)

	def none(self):
		return FakeQuerySet([])

	def __getitem__(self, item):
		if isinstance(item, slice):
			return FakeQuerySet(
				self.rows[item],
				count_value=self.count_value,
				aggregate_value=self.aggregate_value,
			)
		return self.rows[item]

	def __iter__(self):
		return iter(self.rows)

	def __len__(self):
		return len(self.rows)


def make_book_candidate_manager(rows):
	candidate_qs = FakeQuerySet(rows=rows)
	ordered = SimpleNamespace(order_by=MagicMock(return_value=candidate_qs))
	filtered = SimpleNamespace(filter=MagicMock(return_value=ordered))
	manager = SimpleNamespace(exclude=MagicMock(return_value=filtered))
	return manager, candidate_qs


class SearchServiceTests(SimpleTestCase):
	def test_build_search_query_falls_back_to_plain_search_when_websearch_fails(self):
		calls = []

		def fake_search_query(raw_query, search_type, config):
			calls.append((raw_query, search_type, config))
			if len(calls) == 1:
				raise ValueError('websearch not supported')
			return {
				'raw_query': raw_query,
				'search_type': search_type,
				'config': config,
			}

		with patch('books.services.search.SearchQuery', side_effect=fake_search_query):
			query = build_search_query('great gatsby')

		self.assertEqual(query['search_type'], 'plain')
		self.assertEqual(calls[0][1], 'websearch')
		self.assertEqual(calls[1][1], 'plain')

	def test_full_text_search_returns_none_for_blank_queries(self):
		queryset = FakeQuerySet(rows=[SimpleNamespace(title='Book')])

		result = full_text_search('   ', queryset=queryset)

		self.assertEqual(list(result), [])

	def test_full_text_search_applies_rank_filter_and_ordering(self):
		search_query = object()
		queryset = FakeQuerySet(rows=[SimpleNamespace(title='Book', rank=0.9)])

		with patch('books.services.search.build_search_query', return_value=search_query):
			result = full_text_search('fiction', queryset=queryset, min_rank=0.2)

		self.assertIs(result, queryset)
		self.assertIn(('filter', {'search_vector': search_query}), queryset.calls)
		self.assertIn(('filter', {'rank__gte': 0.2}), queryset.calls)
		self.assertIn(('order_by', ('-rank',)), queryset.calls)

	def test_full_text_search_uses_default_queryset_when_none_is_passed(self):
		search_query = object()
		queryset = FakeQuerySet(rows=[SimpleNamespace(title='Book', rank=0.9)])
		manager = SimpleNamespace(all=MagicMock(return_value=queryset))

		with patch('books.services.search.build_search_query', return_value=search_query), \
			 patch('books.services.search.Book.objects', manager):
			result = full_text_search('fiction')

		self.assertIs(result, queryset)
		manager.all.assert_called_once_with()

	def test_wilson_score_lower_bound_handles_zero_votes_and_positive_votes(self):
		self.assertEqual(wilson_score_lower_bound(0, 0), 0.0)
		self.assertGreater(wilson_score_lower_bound(9, 10), 0.0)

	def test_reciprocal_rank_fusion_combines_unique_and_shared_books(self):
		book_a = SimpleNamespace(id='a', title='A')
		book_b = SimpleNamespace(id='b', title='B')
		book_c = SimpleNamespace(id='c', title='C')

		merged = reciprocal_rank_fusion([book_a, book_b], [book_b, book_c], k=60, fts_weight=0.7, popularity_weight=0.3)

		self.assertEqual([book.title for book, _ in merged], ['B', 'A', 'C'])
		self.assertGreater(merged[0][1], merged[1][1])

	def test_rebuild_search_vector_uses_single_update(self):
		manager = MagicMock()
		manager.filter.return_value = manager
		with patch('books.services.search.Book.objects', manager), \
			 patch('books.services.search.SEARCH_VECTOR', 'vector-expression'):
			rebuild_search_vector(SimpleNamespace(pk='book-id'))

		manager.filter.assert_called_once_with(pk='book-id')
		manager.update.assert_called_once_with(search_vector='vector-expression')

	def test_rebuild_all_search_vectors_returns_update_count(self):
		manager = MagicMock()
		manager.update.return_value = 7
		with patch('books.services.search.Book.objects', manager), \
			 patch('books.services.search.SEARCH_VECTOR', 'vector-expression'):
			updated = rebuild_all_search_vectors()

		self.assertEqual(updated, 7)
		manager.update.assert_called_once_with(search_vector='vector-expression')

	def test_hybrid_search_returns_empty_payload_when_both_sources_are_empty(self):
		queryset = FakeQuerySet(rows=[])

		with patch('books.services.search.full_text_search', return_value=FakeQuerySet([])):
			result = hybrid_search('missing title', queryset=queryset, page=2, page_size=5)

		self.assertEqual(result['results'], [])
		self.assertEqual(result['count'], 0)
		self.assertEqual(result['total_pages'], 0)
		self.assertEqual(result['page'], 2)
		self.assertEqual(result['page_size'], 5)

	def test_hybrid_search_merges_ranked_and_popular_books(self):
		fts_book = SimpleNamespace(id='1', title='Alpha', upvote_count=9, downvote_count=1, average_rating=4.7, rating_count=30)
		popular_book = SimpleNamespace(id='2', title='Beta', upvote_count=8, downvote_count=2, average_rating=4.8, rating_count=40)
		queryset = FakeQuerySet(rows=[fts_book, popular_book])
		fts_results = FakeQuerySet(rows=[fts_book, popular_book])

		with patch('books.services.search.full_text_search', return_value=fts_results):
			result = hybrid_search('alpha', queryset=queryset, page=1, page_size=10)

		self.assertEqual(result['count'], 2)
		self.assertEqual(result['results'][0][0].title, 'Alpha')
		self.assertEqual(result['results'][1][0].title, 'Beta')

	def test_hybrid_search_uses_default_queryset_when_none_is_passed(self):
		queryset = FakeQuerySet(rows=[])
		manager = SimpleNamespace(all=MagicMock(return_value=queryset))

		with patch('books.services.search.full_text_search', return_value=FakeQuerySet([])), \
			 patch('books.models.Book', SimpleNamespace(objects=manager)):
			result = hybrid_search('missing title')

		self.assertEqual(result['results'], [])
		manager.all.assert_called_once_with()


class AnalyticsServiceTests(SimpleTestCase):
	def test_get_genre_trends_formats_months_and_scores(self):
		rows = FakeQuerySet(rows=[
			{'genre': 'Fiction', 'month': datetime(2025, 1, 1, tzinfo=timezone.utc), 'avg_rating': 4.25, 'rating_count': 10},
			{'genre': 'Mystery', 'month': datetime(2025, 2, 1, tzinfo=timezone.utc), 'avg_rating': 3.5, 'rating_count': 4},
		])
		manager = SimpleNamespace(filter=MagicMock(return_value=rows))

		with patch('books.models.BookRating', SimpleNamespace(objects=manager)):
			trends = get_genre_trends(months=6)

		self.assertEqual(trends[0]['month'], '2025-01')
		self.assertEqual(trends[0]['avg_rating'], 4.25)
		self.assertEqual(trends[1]['rating_count'], 4)

	def test_get_top_genres_by_quality_excludes_small_genres(self):
		rows = FakeQuerySet(rows=[
			{'genre': 'Fiction', 'book_count': 8, 'avg_quality': 0.9123, 'flagged_count': 1},
			{'genre': 'Mystery', 'book_count': 5, 'avg_quality': 0.8456, 'flagged_count': 0},
		])
		manager = SimpleNamespace(filter=MagicMock(return_value=rows))

		with patch('books.models.Book', SimpleNamespace(objects=manager)):
			results = get_top_genres_by_quality(limit=2)

		self.assertEqual(results[0]['avg_quality_score'], 0.912)
		self.assertEqual(results[0]['flagged_pct'], 12.5)
		self.assertEqual(len(results), 2)

	def test_get_catalogue_summary_assembles_key_metrics(self):
		genre_dist = FakeQuerySet(rows=[
			{'genre': 'Fiction', 'count': 2},
			{'genre': 'Mystery', 'count': 1},
		])
		most_rated = FakeQuerySet(rows=[
			{'id': 'book-1', 'title': 'Alpha', 'genre': 'Fiction', 'rating_count': 12, 'average_rating': 4.6},
			{'id': 'book-2', 'title': 'Beta', 'genre': 'Mystery', 'rating_count': 8, 'average_rating': 4.3},
		])
		wilson_candidates = FakeQuerySet(rows=[
			SimpleNamespace(id='book-1', title='Alpha', genre='Fiction', average_rating=4.6, rating_count=12, upvote_count=10, downvote_count=2),
			SimpleNamespace(id='book-2', title='Beta', genre='Mystery', average_rating=4.3, rating_count=8, upvote_count=6, downvote_count=2),
		])
		recent_books = FakeQuerySet(rows=[
			{'id': 'book-3', 'title': 'Gamma', 'genre': 'History', 'quality_score': 0.0, 'created_at': datetime(2025, 3, 1, tzinfo=timezone.utc)},
		])
		excellent = FakeQuerySet(count_value=3)
		good = FakeQuerySet(count_value=2)
		fair = FakeQuerySet(count_value=1)
		poor = FakeQuerySet(count_value=0)

		book_objects = SimpleNamespace(
			count=MagicMock(return_value=4),
			aggregate=MagicMock(return_value={'avg': 0.8125}),
			filter=MagicMock(side_effect=[
				FakeQuerySet(count_value=1),
				most_rated,
				wilson_candidates,
				excellent,
				good,
				fair,
				poor,
			]),
			exclude=MagicMock(return_value=genre_dist),
			order_by=MagicMock(return_value=recent_books),
		)
		book_rating_objects = SimpleNamespace(
			count=MagicMock(return_value=5),
			aggregate=MagicMock(return_value={'avg': 4.2}),
		)
		import_job_objects = SimpleNamespace(
			aggregate=MagicMock(return_value={'total_jobs': 3, 'total_imported': 2, 'total_books_imported': 2}),
		)

		with patch('books.models.Book', SimpleNamespace(objects=book_objects)), \
			 patch('books.models.BookRating', SimpleNamespace(objects=book_rating_objects)), \
			 patch('books.models.ImportJob', SimpleNamespace(objects=import_job_objects)):
			summary = get_catalogue_summary()

		self.assertEqual(summary['catalogue_health']['total_books'], 4)
		self.assertEqual(summary['catalogue_health']['flagged_pct'], 25.0)
		self.assertEqual(summary['rating_statistics']['total_ratings'], 5)
		self.assertEqual(summary['genre_distribution'][0]['genre'], 'Fiction')
		self.assertEqual(summary['top_books_by_wilson_score'][0]['title'], 'Alpha')
		self.assertEqual(summary['import_history']['completed_jobs'], 2)
		self.assertEqual(summary['recent_additions'][0]['title'], 'Gamma')


class RecommenderServiceTests(SimpleTestCase):
	def test_build_taste_profile_collects_liked_books_and_ids(self):
		liked_ratings = FakeQuerySet(rows=[
			SimpleNamespace(book=SimpleNamespace(id='book-1', genre='Fiction', normalized_author='Author One')),
			SimpleNamespace(book=SimpleNamespace(id='book-2', genre='Mystery', normalized_author='Author Two')),
		])
		all_rated = FakeQuerySet(rows=['book-1', 'book-2', 'book-3'])
		manager = SimpleNamespace(
			filter=MagicMock(side_effect=[liked_ratings, all_rated]),
		)

		with patch('books.models.BookRating', SimpleNamespace(objects=manager)):
			profile = build_taste_profile(SimpleNamespace(username='reader'))

		self.assertEqual(profile['liked_genres'], Counter({'Fiction': 1, 'Mystery': 1}))
		self.assertEqual(profile['liked_authors'], Counter({'Author One': 1, 'Author Two': 1}))
		self.assertEqual(profile['liked_book_ids'], {'book-1', 'book-2'})
		self.assertEqual(profile['all_rated_ids'], {'book-1', 'book-2', 'book-3'})
		self.assertTrue(profile['has_ratings'])

	def test_content_based_recommendations_returns_no_ratings_when_profile_is_empty(self):
		with patch('books.services.recommender.build_taste_profile', return_value={'has_ratings': False}):
			results, strategy = content_based_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, [])
		self.assertEqual(strategy, 'no_ratings')

	def test_content_based_recommendations_scores_matching_books(self):
		profile = {
			'liked_genres': Counter({'Fiction': 2}),
			'liked_authors': Counter({'Author A': 2}),
			'liked_book_ids': {'book-1'},
			'all_rated_ids': {'book-1'},
			'has_ratings': True,
		}
		books = FakeQuerySet(rows=[
			SimpleNamespace(id='book-2', title='Match', genre='Fiction', normalized_author='Author A', quality_score=0.8, average_rating=4.5),
			SimpleNamespace(id='book-3', title='Partial', genre='Fiction', normalized_author='Someone Else', quality_score=0.5, average_rating=4.1),
		])
		manager, _ = make_book_candidate_manager(books.rows)

		with patch('books.models.Book', SimpleNamespace(objects=manager)), \
			 patch('books.services.recommender.build_taste_profile', return_value=profile):
			results, strategy = content_based_recommendations(SimpleNamespace(username='reader'), limit=2)

		self.assertEqual(strategy, 'content_based')
		self.assertEqual([book.title for book in results], ['Match', 'Partial'])

	def test_content_based_recommendations_uses_secondary_genre_and_author_matches(self):
		profile = {
			'liked_genres': Counter({'Fiction': 1, 'Mystery': 1}),
			'liked_authors': Counter({'Author A': 1, 'Author B': 1}),
			'liked_book_ids': {'book-1'},
			'all_rated_ids': {'book-1'},
			'has_ratings': True,
		}
		books = FakeQuerySet(rows=[
			SimpleNamespace(id='book-2', title='Secondary Match', genre='Mystery', normalized_author='Author B', quality_score=0.4, average_rating=4.1),
		])
		manager, _ = make_book_candidate_manager(books.rows)

		with patch('books.models.Book', SimpleNamespace(objects=manager)), \
			 patch('books.services.recommender.build_taste_profile', return_value=profile):
			results, strategy = content_based_recommendations(SimpleNamespace(username='reader'), limit=1)

		self.assertEqual(strategy, 'content_based')
		self.assertEqual([book.title for book in results], ['Secondary Match'])

	def test_collaborative_recommendations_returns_no_ratings_when_profile_is_empty(self):
		with patch('books.services.recommender.build_taste_profile', return_value={'has_ratings': False}):
			results, strategy = collaborative_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, [])
		self.assertEqual(strategy, 'no_ratings')

	def test_content_based_recommendations_returns_no_matches_when_candidates_score_zero(self):
		profile = {
			'liked_genres': Counter({'Mystery': 1}),
			'liked_authors': Counter({'Author A': 1}),
			'liked_book_ids': {'book-1'},
			'all_rated_ids': {'book-1'},
			'has_ratings': True,
		}
		books = FakeQuerySet(rows=[
			SimpleNamespace(id='book-2', title='Unrelated', genre='History', normalized_author='Different Author', quality_score=0.0, average_rating=3.0),
		])
		manager, _ = make_book_candidate_manager(books.rows)

		with patch('books.models.Book', SimpleNamespace(objects=manager)), \
			 patch('books.services.recommender.build_taste_profile', return_value=profile):
			results, strategy = content_based_recommendations(SimpleNamespace(username='reader'), limit=2)

		self.assertEqual(results, [])
		self.assertEqual(strategy, 'no_matches')

	def test_collaborative_recommendations_returns_no_similar_users_when_overlap_is_missing(self):
		profile = {
			'liked_genres': Counter({'Fiction': 1}),
			'liked_authors': Counter(),
			'liked_book_ids': {'book-1'},
			'all_rated_ids': {'book-1'},
			'has_ratings': True,
		}
		co_raters = FakeQuerySet(rows=[])
		manager = SimpleNamespace(
			filter=MagicMock(return_value=SimpleNamespace(
				exclude=MagicMock(return_value=SimpleNamespace(
					values_list=MagicMock(return_value=SimpleNamespace(
						distinct=MagicMock(return_value=co_raters),
					)),
				)),
			)),
		)

		with patch('books.models.BookRating', SimpleNamespace(objects=manager)), \
			 patch('books.services.recommender.build_taste_profile', return_value=profile):
			results, strategy = collaborative_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, [])
		self.assertEqual(strategy, 'no_similar_users')

	def test_collaborative_recommendations_returns_no_similar_users_when_overlap_has_zero_jaccard(self):
		profile = {
			'liked_genres': Counter({'Fiction': 1}),
			'liked_authors': Counter(),
			'liked_book_ids': {'book-1'},
			'all_rated_ids': {'book-1'},
			'has_ratings': True,
		}
		co_raters = FakeQuerySet(rows=['user-2'])
		other_liked = FakeQuerySet(rows=['book-9'])
		manager = SimpleNamespace(
			filter=MagicMock(side_effect=[
				SimpleNamespace(
					exclude=MagicMock(return_value=SimpleNamespace(
						values_list=MagicMock(return_value=SimpleNamespace(
							distinct=MagicMock(return_value=co_raters),
						)),
					)),
				),
				other_liked,
			]),
		)

		with patch('books.models.BookRating', SimpleNamespace(objects=manager)), \
			 patch('books.services.recommender.build_taste_profile', return_value=profile):
			results, strategy = collaborative_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, [])
		self.assertEqual(strategy, 'no_similar_users')

	def test_collaborative_recommendations_returns_no_new_books_when_everything_was_rated(self):
		profile = {
			'liked_genres': Counter({'Fiction': 1}),
			'liked_authors': Counter(),
			'liked_book_ids': {'book-1'},
			'all_rated_ids': {'book-1'},
			'has_ratings': True,
		}
		co_raters = FakeQuerySet(rows=['user-2'])
		other_liked = FakeQuerySet(rows=['book-1'])
		manager = SimpleNamespace(
			filter=MagicMock(side_effect=[
				SimpleNamespace(
					exclude=MagicMock(return_value=SimpleNamespace(
						values_list=MagicMock(return_value=SimpleNamespace(
							distinct=MagicMock(return_value=co_raters),
						)),
					)),
				),
				other_liked,
			]),
		)

		with patch('books.models.BookRating', SimpleNamespace(objects=manager)), \
			 patch('books.services.recommender.build_taste_profile', return_value=profile):
			results, strategy = collaborative_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, [])
		self.assertEqual(strategy, 'no_new_books')

	def test_collaborative_recommendations_returns_ranked_books_for_similar_users(self):
		profile = {
			'liked_genres': Counter({'Fiction': 1}),
			'liked_authors': Counter(),
			'liked_book_ids': {'book-1'},
			'all_rated_ids': {'book-1'},
			'has_ratings': True,
		}
		co_raters = FakeQuerySet(rows=['user-2'])
		other_liked = FakeQuerySet(rows=['book-1', 'book-2'])
		recommended_books = FakeQuerySet(rows=[
			SimpleNamespace(id='book-2', title='Suggested One'),
		])
		manager = SimpleNamespace(
			filter=MagicMock(side_effect=[
				SimpleNamespace(
					exclude=MagicMock(return_value=SimpleNamespace(
						values_list=MagicMock(return_value=SimpleNamespace(
							distinct=MagicMock(return_value=co_raters),
						)),
					)),
				),
				other_liked,
				recommended_books,
			]),
		)

		with patch('books.models.BookRating', SimpleNamespace(objects=manager)), \
			 patch('books.models.Book', SimpleNamespace(objects=SimpleNamespace(filter=MagicMock(return_value=recommended_books)))), \
			 patch('books.services.recommender.build_taste_profile', return_value=profile):
			results, strategy = collaborative_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(strategy, 'collaborative')
		self.assertEqual([book.title for book in results], ['Suggested One'])

	def test_popularity_recommendations_orders_by_wilson_score(self):
		books = FakeQuerySet(rows=[
			SimpleNamespace(id='book-1', title='Strong', upvote_count=20, downvote_count=1, average_rating=4.8, rating_count=30),
			SimpleNamespace(id='book-2', title='Weaker', upvote_count=8, downvote_count=4, average_rating=4.7, rating_count=35),
		])
		manager, _ = make_book_candidate_manager(books.rows)

		with patch('books.models.Book', SimpleNamespace(objects=manager)):
			results, strategy = popularity_recommendations(limit=2)

		self.assertEqual(strategy, 'popularity_wilson_score')
		self.assertEqual(results[0].title, 'Strong')

	def test_get_recommendations_falls_back_to_popularity(self):
		profile = {'all_rated_ids': {'book-1', 'book-2'}}
		popular = [SimpleNamespace(title='Fallback Book')]

		with patch('books.services.recommender.content_based_recommendations', return_value=([], 'no_matches')) as mock_content, \
			 patch('books.services.recommender.collaborative_recommendations', return_value=([], 'no_new_books')) as mock_collab, \
			 patch('books.services.recommender.build_taste_profile', return_value=profile) as mock_profile, \
			 patch('books.services.recommender.popularity_recommendations', return_value=(popular, 'popularity_wilson_score')) as mock_popularity:
			results, strategy = get_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, popular)
		self.assertEqual(strategy, 'popularity_wilson_score')
		mock_content.assert_called_once()
		mock_collab.assert_called_once()
		mock_profile.assert_called_once()
		mock_popularity.assert_called_once_with(limit=20, exclude_ids={'book-1', 'book-2'})

	def test_get_recommendations_returns_content_based_results_without_fallback(self):
		recommended = [SimpleNamespace(title='Recommended Book')]

		with patch('books.services.recommender.content_based_recommendations', return_value=(recommended, 'content_based')) as mock_content, \
			 patch('books.services.recommender.collaborative_recommendations') as mock_collab, \
			 patch('books.services.recommender.popularity_recommendations') as mock_popularity:
			results, strategy = get_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, recommended)
		self.assertEqual(strategy, 'content_based')
		mock_content.assert_called_once()
		mock_collab.assert_not_called()
		mock_popularity.assert_not_called()

	def test_get_recommendations_returns_collaborative_results_when_content_based_is_empty(self):
		recommended = [SimpleNamespace(title='Collaborative Book')]

		with patch('books.services.recommender.content_based_recommendations', return_value=([], 'no_matches')) as mock_content, \
			 patch('books.services.recommender.collaborative_recommendations', return_value=(recommended, 'collaborative')) as mock_collab, \
			 patch('books.services.recommender.popularity_recommendations') as mock_popularity:
			results, strategy = get_recommendations(SimpleNamespace(username='reader'))

		self.assertEqual(results, recommended)
		self.assertEqual(strategy, 'collaborative')
		mock_content.assert_called_once()
		mock_collab.assert_called_once()
		mock_popularity.assert_not_called()
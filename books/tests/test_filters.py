"""Filter helper tests for BookIQ."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from books.filters import BookFilter


class BookFilterTests(SimpleTestCase):
	def test_filter_keyword_returns_original_queryset_for_empty_value(self):
		queryset = MagicMock()
		book_filter = BookFilter(data={}, queryset=queryset)

		result = book_filter.filter_keyword(queryset, 'q', '')

		self.assertIs(result, queryset)
		queryset.filter.assert_not_called()

	def test_filter_keyword_applies_or_query_and_distinct(self):
		queryset = MagicMock()
		filtered = MagicMock()
		queryset.filter.return_value = filtered
		filtered.distinct.return_value = filtered
		book_filter = BookFilter(data={}, queryset=queryset)

		result = book_filter.filter_keyword(queryset, 'q', 'gatsby')

		self.assertIs(result, filtered)
		queryset.filter.assert_called_once()
		filtered.distinct.assert_called_once()
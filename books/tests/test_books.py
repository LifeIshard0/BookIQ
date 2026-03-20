"""Book endpoint tests for CRUD, RBAC, and key HTTP response codes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.http import Http404
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from books.models import BookRating
from books.views import BookViewSet


class BookApiTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.reader = SimpleNamespace(username='reader', role='reader', is_authenticated=True)
		self.curator = SimpleNamespace(username='curator', role='curator', is_authenticated=True)
		self.admin = SimpleNamespace(username='admin', role='admin', is_authenticated=True)

	# RBAC: readers can not create books.
	def test_reader_cannot_create_book_but_curator_can(self):
		payload = {
			'title': 'New Book',
			'author': 'New Author',
			'isbn_13': '9780306406159',
			'description': 'A new curated book.',
			'genre': 'Fantasy',
			'published_year': 2002,
			'publisher': 'Publisher',
			'page_count': 123,
			'language': 'en',
			'cover_url': 'https://example.com/new.jpg',
		}

		reader_request = self.factory.post(reverse('book-list'), payload, format='json')
		force_authenticate(reader_request, user=self.reader)
		reader_response = BookViewSet.as_view({'post': 'create'})(reader_request)
		self.assertEqual(reader_response.status_code, 403)

		# Curators can create and the serializer should attach created_by.
		curator_request = self.factory.post(reverse('book-list'), payload, format='json')
		force_authenticate(curator_request, user=self.curator)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.data = {'created_by_username': 'curator', 'title': 'New Book'}
		serializer.save.return_value = SimpleNamespace()

		with patch.object(BookViewSet, 'get_serializer', return_value=serializer):
			curator_response = BookViewSet.as_view({'post': 'create'})(curator_request)

		self.assertEqual(curator_response.status_code, 201)
		self.assertEqual(curator_response.data['created_by_username'], 'curator')
		serializer.save.assert_called_once()

	# Duplicate ISBNs should be converted into a 409 response.
	def test_duplicate_isbn_returns_conflict(self):
		payload = {
			'title': 'Duplicate Book',
			'author': 'Another Author',
			'isbn_13': '9780306406157',
			'description': 'Same ISBN as an existing book.',
			'genre': 'Fantasy',
			'published_year': 2003,
			'publisher': 'Publisher',
			'page_count': 200,
			'language': 'en',
			'cover_url': 'https://example.com/duplicate.jpg',
		}

		request = self.factory.post(reverse('book-list'), payload, format='json')
		force_authenticate(request, user=self.curator)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.save.side_effect = IntegrityError()
		serializer.data = {}

		with patch.object(BookViewSet, 'get_serializer', return_value=serializer):
			response = BookViewSet.as_view({'post': 'create'})(request)

		self.assertEqual(response.status_code, 409)

	# Unauthenticated create requests should be rejected by the auth layer.
	def test_unauthenticated_create_returns_401(self):
		request = self.factory.post(
			reverse('book-list'),
			{
				'title': 'Unauthorized',
				'author': 'Author',
				'isbn_13': '9780306406161',
				'description': 'No credentials.',
				'genre': 'Fantasy',
				'published_year': 2004,
				'publisher': 'Publisher',
				'page_count': 210,
				'language': 'en',
				'cover_url': 'https://example.com/unauthorized.jpg',
			},
			format='json'
		)

		response = BookViewSet.as_view({'post': 'create'})(request)
		self.assertEqual(response.status_code, 401)

	# A missing book should produce the standard 404 response.
	def test_retrieve_missing_book_returns_404(self):
		request = self.factory.get(reverse('book-detail', args=['missing-book']))
		force_authenticate(request, user=self.reader)

		with patch.object(BookViewSet, 'get_object', side_effect=Http404()):
			response = BookViewSet.as_view({'get': 'retrieve'})(request, pk='missing-book')

		self.assertEqual(response.status_code, 404)

	# Delete uses the admin-only RBAC path and returns a custom success message.
	def test_destroy_book_returns_message_for_admin(self):
		request = self.factory.delete(reverse('book-detail', args=['book-id']))
		force_authenticate(request, user=self.admin)

		fake_book = SimpleNamespace(title='Delete Me')
		with patch.object(BookViewSet, 'get_object', return_value=fake_book), \
			 patch.object(BookViewSet, 'perform_destroy') as mock_destroy:
			response = BookViewSet.as_view({'delete': 'destroy'})(request, pk='book-id')

		self.assertEqual(response.status_code, 204)
		self.assertEqual(response.data['message'], "Book 'Delete Me' deleted successfully.")
		mock_destroy.assert_called_once_with(fake_book)

	# Partial update is part of CRUD coverage.
	def test_partial_update_returns_200_for_curator(self):
		request = self.factory.patch(
			reverse('book-detail', args=['book-id']),
			{'title': 'Updated Title'},
			format='json'
		)
		force_authenticate(request, user=self.curator)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.data = {'title': 'Updated Title'}
		serializer.save.return_value = None

		with patch.object(BookViewSet, 'get_object', return_value=SimpleNamespace(pk='book-id')), \
			 patch.object(BookViewSet, 'get_serializer', return_value=serializer):
			response = BookViewSet.as_view({'patch': 'partial_update'})(request, pk='book-id')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['title'], 'Updated Title')

	def test_authenticated_user_can_rate_book(self):
		request = self.factory.post(
			reverse('book-rate', args=['book-id']),
			{'rating': 5, 'review': 'Strong recommendation.'},
			format='json'
		)
		force_authenticate(request, user=self.reader)

		fake_book = SimpleNamespace(pk='book-id')
		fake_rating = SimpleNamespace(
			user=SimpleNamespace(username='reader'),
			vote_type='upvote',
			rating=5,
			review='Strong recommendation.',
			created_at=datetime.now(timezone.utc),
			updated_at=datetime.now(timezone.utc),
			book=SimpleNamespace(pk='book-id', title='Book Title'),
			id='rating-id',
		)

		with patch.object(BookViewSet, 'get_object', return_value=fake_book), \
			 patch('books.views.BookRating.objects.update_or_create', return_value=(fake_rating, True)):
			response = BookViewSet.as_view({'post': 'rate'})(request, pk='book-id')

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.data['vote_type'], 'upvote')

	def test_authenticated_user_can_fetch_my_rating(self):
		request = self.factory.get(
			reverse('book-my-rating', args=['book-id'])
		)
		force_authenticate(request, user=self.reader)

		fake_book = SimpleNamespace(pk='book-id')
		fake_rating = SimpleNamespace(
			user=SimpleNamespace(username='reader'),
			book=SimpleNamespace(pk='book-id', title='My Rated Book'),
			vote_type='upvote',
			rating=4,
			review='Helpful and concise.',
			created_at=datetime.now(timezone.utc),
			updated_at=datetime.now(timezone.utc),
			id='rating-id',
		)

		with patch.object(BookViewSet, 'get_object', return_value=fake_book), \
			 patch('books.views.BookRating.objects.get', return_value=fake_rating):
			response = BookViewSet.as_view({'get': 'my_rating'})(request, pk='book-id')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['book_title'], 'My Rated Book')
		self.assertEqual(response.data['username'], 'reader')

	def test_vote_type_is_neutral_when_rating_is_missing(self):
		rating = BookRating(rating=None)

		self.assertEqual(rating.vote_type, 'neutral')

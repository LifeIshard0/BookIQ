import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied as DjangoPermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from django.db import IntegrityError
from django.test import Client, RequestFactory, SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied as DRFPermissionDenied

from books.exceptions import _make_error_response, global_exception_handler, handler_404, handler_500
from books.views import BookViewSet


class ExceptionEnvelopeTests(SimpleTestCase):

	def setUp(self):
		self.client = Client()
		self.api_factory = APIRequestFactory()
		self.request_factory = RequestFactory()
		self.reader = SimpleNamespace(username='reader', role='reader', is_authenticated=True)
		self.curator = SimpleNamespace(username='curator', role='curator', is_authenticated=True)

	def test_invalid_book_uuid_returns_standard_404_envelope(self):
		request = self.api_factory.get('/api/books/00000000-0000-0000-0000-000000000000/')

		with patch.object(
			BookViewSet,
			'get_object',
			side_effect=Http404('No Book matches the given query.')
		):
			response = BookViewSet.as_view({'get': 'retrieve'})(
				request,
				pk='00000000-0000-0000-0000-000000000000'
			)

		self.assertEqual(response.status_code, 404)
		self.assertEqual(
			response.data,
			{
				'error': True,
				'status_code': 404,
				'detail': 'No Book matches the given query.',
			}
		)

	def test_missing_url_returns_custom_404_envelope(self):
		response = self.client.get('/api/doesnotexist/')

		self.assertEqual(response.status_code, 404)
		self.assertEqual(
			response.json(),
			{
				'error': True,
				'status_code': 404,
				'detail': 'Endpoint not found: /api/doesnotexist/',
			}
		)

	def test_unauthenticated_create_book_returns_401_envelope(self):
		request = self.api_factory.post(
			'/api/books/',
			{'title': 'Test'},
			format='json'
		)

		response = BookViewSet.as_view({'post': 'create'})(request)

		self.assertEqual(response.status_code, 401)
		self.assertEqual(
			response.data,
			{
				'error': True,
				'status_code': 401,
				'detail': 'Authentication credentials were not provided.',
			}
		)

	def test_reader_cannot_create_book_returns_403_envelope(self):
		request = self.api_factory.post(
			'/api/books/',
			{'title': 'Test', 'isbn_13': '9780000000000'},
			format='json'
		)
		force_authenticate(request, user=self.reader)

		response = BookViewSet.as_view({'post': 'create'})(request)

		self.assertEqual(response.status_code, 403)
		self.assertEqual(
			response.data,
			{
				'error': True,
				'status_code': 403,
				'detail': 'You do not have permission to perform this action.',
			}
		)

	def test_invalid_book_data_returns_validation_envelope(self):
		request = self.api_factory.post(
			'/api/books/',
			{'title': '', 'author': 'Test Author'},
			format='json'
		)
		force_authenticate(request, user=self.curator)

		response = BookViewSet.as_view({'post': 'create'})(request)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(
			response.data,
			{
				'error': True,
				'status_code': 400,
				'detail': {
					'title': ['This field may not be blank.'],
					'isbn_13': ['This field is required.'],
				},
			}
		)

	def test_duplicate_isbn_returns_conflict_envelope(self):
		request = self.api_factory.post(
			'/api/books/',
			{
				'title': 'Duplicate',
				'author': 'Test Author',
				'isbn_13': '9780000000000',
			},
			format='json'
		)
		force_authenticate(request, user=self.curator)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.data = {'title': 'Duplicate', 'isbn_13': '9780000000000'}
		serializer.save.side_effect = IntegrityError()

		with patch.object(BookViewSet, 'get_serializer', return_value=serializer):
			response = BookViewSet.as_view({'post': 'create'})(request)

		self.assertEqual(response.status_code, 409)
		self.assertEqual(
			response.data,
			{
				'error': True,
				'status_code': 409,
				'detail': 'A book with this ISBN-13 already exists.',
			}
		)

	def test_invalid_rating_value_returns_validation_envelope(self):
		request = self.api_factory.post(
			'/api/books/book-id/rate/',
			{'rating': 9},
			format='json'
		)
		force_authenticate(request, user=self.reader)

		with patch.object(BookViewSet, 'get_object', return_value=SimpleNamespace(pk='book-id')):
			response = BookViewSet.as_view({'post': 'rate'})(request, pk='book-id')

		self.assertEqual(response.status_code, 400)
		self.assertEqual(
			response.data,
			{
				'error': True,
				'status_code': 400,
				'detail': {
					'rating': ['Ensure this value is less than or equal to 5.']
				},
			}
		)

	def test_invalid_token_returns_401_envelope(self):
		request = self.api_factory.get(
			'/api/books/recommendations/',
			HTTP_AUTHORIZATION='Bearer invalidtoken123'
		)

		response = BookViewSet.as_view({'get': 'recommendations'})(request)

		self.assertEqual(response.status_code, 401)
		self.assertEqual(
			response.data,
			{
				'error': True,
				'status_code': 401,
				'detail': 'Given token not valid for any token type',
			}
		)

	def test_handler500_returns_json_envelope(self):
		request = self.request_factory.get('/api/boom/')
		response = handler_500(request)

		self.assertEqual(response.status_code, 500)
		self.assertEqual(
			json.loads(response.content),
			{
				'error': True,
				'status_code': 500,
				'detail': 'Internal server error. Please try again later.',
			}
		)

	def test_make_error_response_includes_extra_fields(self):
		response = _make_error_response('boom', 418, extra={'hint': 'teapot'})

		self.assertEqual(response.status_code, 418)
		self.assertEqual(response.data['detail'], 'boom')
		self.assertEqual(response.data['hint'], 'teapot')

	def test_global_exception_handler_formats_drf_permission_denied(self):
		request = self.request_factory.get('/api/books/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))

		with patch('books.exceptions.drf_exception_handler', return_value=SimpleNamespace(data={'detail': 'denied'}, status_code=403)):
			response = global_exception_handler(DRFPermissionDenied(), {'request': request, 'view': view})

		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.data['detail'], 'You do not have permission to perform this action.')

	def test_global_exception_handler_unwraps_401_detail(self):
		request = self.request_factory.get('/api/books/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))

		with patch('books.exceptions.drf_exception_handler', return_value=SimpleNamespace(data={'detail': 'Missing token'}, status_code=401)):
			response = global_exception_handler(NotAuthenticated(), {'request': request, 'view': view})

		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.data['detail'], 'Missing token')

	def test_global_exception_handler_preserves_extra_detail_fields(self):
		request = self.request_factory.get('/api/books/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))

		with patch('books.exceptions.drf_exception_handler', return_value=SimpleNamespace(data={'detail': 'Bad', 'code': 'invalid'}, status_code=400)):
			response = global_exception_handler(AuthenticationFailed('Bad'), {'request': request, 'view': view})

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.data['detail']['detail'], 'Bad')
		self.assertEqual(response.data['detail']['code'], 'invalid')

	def test_global_exception_handler_handles_django_http_404(self):
		request = self.request_factory.get('/api/books/missing/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))

		with patch('books.exceptions.drf_exception_handler', return_value=None):
			response = global_exception_handler(Http404('Nope'), {'request': request, 'view': view})

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.data['detail'], 'Nope')

	def test_global_exception_handler_handles_django_permission_denied(self):
		request = self.request_factory.get('/api/books/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))

		with patch('books.exceptions.drf_exception_handler', return_value=None):
			response = global_exception_handler(DjangoPermissionDenied(), {'request': request, 'view': view})

		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.data['detail'], 'You do not have permission to perform this action.')

	def test_global_exception_handler_handles_django_validation_error(self):
		request = self.request_factory.get('/api/books/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))
		validation_error = DjangoValidationError({'title': ['required']})

		with patch('books.exceptions.drf_exception_handler', return_value=None):
			response = global_exception_handler(validation_error, {'request': request, 'view': view})

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.data['detail'], {'title': ['required']})

	def test_global_exception_handler_handles_django_object_does_not_exist(self):
		request = self.request_factory.get('/api/books/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))

		with patch('books.exceptions.drf_exception_handler', return_value=None):
			response = global_exception_handler(ObjectDoesNotExist('Missing object'), {'request': request, 'view': view})

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.data['detail'], 'Missing object')

	def test_global_exception_handler_falls_back_to_500_for_unhandled_errors(self):
		request = self.request_factory.get('/api/books/')
		view = SimpleNamespace(__class__=SimpleNamespace(__name__='BookViewSet'))

		with patch('books.exceptions.drf_exception_handler', return_value=None):
			response = global_exception_handler(RuntimeError('boom'), {'request': request, 'view': view})

		self.assertEqual(response.status_code, 500)
		self.assertEqual(response.data['detail'], 'An unexpected error occurred. Please try again later.')

	def test_handler404_returns_json_envelope(self):
		request = self.request_factory.get('/api/missing/')
		response = handler_404(request)

		self.assertEqual(response.status_code, 404)
		self.assertEqual(json.loads(response.content), {
			'error': True,
			'status_code': 404,
			'detail': 'Endpoint not found: /api/missing/',
		})
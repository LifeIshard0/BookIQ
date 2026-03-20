"""Auth endpoint tests for registration, login, refresh, expiry, and profile handling."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework_simplejwt.exceptions import ExpiredTokenError
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.views import TokenRefreshView

from users.views import (
	CustomTokenObtainPairSerializer,
	CustomTokenObtainPairView,
	ProfileView,
	RegisterView,
)


class AuthApiTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()

	# Registration is handled by DRF's CreateAPIView, so we patch the serializer
	# to keep the test focused on the response contract.
	def test_register_view_uses_serializer_and_returns_created(self):
		request = self.factory.post(
			reverse('auth-register'),
			{
				'username': 'newuser',
				'email': 'newuser@example.com',
				'password': 'StrongPass123!',
				'password2': 'StrongPass123!',
				'role': 'curator',
			},
			format='json'
		)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.data = {'username': 'newuser', 'role': 'curator'}
		serializer.save.return_value = SimpleNamespace()

		with patch.object(RegisterView, 'get_serializer', return_value=serializer):
			response = RegisterView.as_view()(request)

		self.assertEqual(response.status_code, 201)
		serializer.is_valid.assert_called_once()
		serializer.save.assert_called_once()

	# The custom JWT serializer should add the two extra claims we rely on.
	def test_custom_token_serializer_adds_role_and_username_claims(self):
		fake_user = SimpleNamespace(
			id='user-id',
			pk='user-id',
			is_active=True,
			username='loginuser',
			role='admin',
		)

		token = CustomTokenObtainPairSerializer.get_token(fake_user)

		self.assertEqual(token['username'], 'loginuser')
		self.assertEqual(token['role'], 'admin')

	# Login is a normal token pair flow; patch the serializer output rather than
	# forcing a live auth backend dependency into this unit test.
	def test_login_view_returns_access_and_refresh_tokens(self):
		request = self.factory.post(
			reverse('auth-login'),
			{'username': 'loginuser', 'password': 'StrongPass123!'},
			format='json'
		)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.validated_data = {
			'access': 'access-token',
			'refresh': 'refresh-token',
		}

		with patch.object(CustomTokenObtainPairView, 'get_serializer', return_value=serializer):
			response = CustomTokenObtainPairView.as_view()(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['access'], 'access-token')
		self.assertEqual(response.data['refresh'], 'refresh-token')

	# Expiry is deterministic when we explicitly set an expired exp claim.
	def test_expired_token_is_rejected(self):
		token = AccessToken()
		token.set_exp(
			from_time=datetime.now(timezone.utc) - timedelta(days=1),
			lifetime=timedelta(seconds=1)
		)

		with self.assertRaises(ExpiredTokenError):
			AccessToken(str(token))

	# Refresh should return a new access token when the refresh serializer accepts
	# the incoming refresh token.
	def test_refresh_view_returns_new_access_token(self):
		request = self.factory.post(
			reverse('token-refresh'),
			{'refresh': 'old-refresh-token'},
			format='json'
		)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.validated_data = {'access': 'new-access-token'}

		with patch.object(TokenRefreshView, 'get_serializer', return_value=serializer):
			response = TokenRefreshView.as_view()(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['access'], 'new-access-token')

	def test_profile_view_get_and_patch(self):
		fake_user = SimpleNamespace(
			is_authenticated=True,
			id='user-id',
			username='profileuser',
			email='profileuser@example.com',
			role='reader',
			bio='Original bio',
			created_at=datetime.now(timezone.utc),
		)

		unauthenticated_request = self.factory.get(reverse('auth-profile'))
		unauthenticated_response = ProfileView.as_view()(unauthenticated_request)
		self.assertEqual(unauthenticated_response.status_code, 401)

		authenticated_request = self.factory.get(reverse('auth-profile'))
		force_authenticate(authenticated_request, user=fake_user)
		authenticated_response = ProfileView.as_view()(authenticated_request)
		self.assertEqual(authenticated_response.status_code, 200)
		self.assertEqual(authenticated_response.data['username'], 'profileuser')
		self.assertEqual(authenticated_response.data['bio'], 'Original bio')

		patch_request = self.factory.patch(
			reverse('auth-profile'),
			{'bio': 'Updated bio'},
			format='json'
		)
		force_authenticate(patch_request, user=fake_user)

		serializer = MagicMock()
		serializer.is_valid.return_value = True
		serializer.data = {
			'id': 'user-id',
			'username': 'profileuser',
			'email': 'profileuser@example.com',
			'role': 'reader',
			'bio': 'Updated bio',
			'created_at': fake_user.created_at,
		}
		serializer.save.return_value = None

		with patch('users.views.UserProfileSerializer', return_value=serializer):
			patch_response = ProfileView.as_view()(patch_request)

		self.assertEqual(patch_response.status_code, 200)
		self.assertEqual(patch_response.data['bio'], 'Updated bio')
		serializer.is_valid.assert_called_once()
		serializer.save.assert_called_once()

	def test_register_view_returns_400_for_validation_errors(self):
		request = self.factory.post(
			reverse('auth-register'),
			{
				'username': 'newuser',
				'email': 'newuser@example.com',
				'password': 'StrongPass123!',
				'password2': 'Mismatch123!',
			},
			format='json'
		)

		serializer = MagicMock()
		serializer.is_valid.side_effect = ValidationError({'password': ['Passwords do not match.']})

		with patch.object(RegisterView, 'get_serializer', return_value=serializer):
			response = RegisterView.as_view()(request)

		self.assertEqual(response.status_code, 400)
		serializer.save.assert_not_called()

	def test_login_view_returns_401_for_invalid_credentials(self):
		request = self.factory.post(
			reverse('auth-login'),
			{'username': 'loginuser', 'password': 'WrongPass123!'},
			format='json'
		)

		serializer = MagicMock()
		serializer.is_valid.side_effect = AuthenticationFailed(
			'No active account found with the given credentials'
		)

		with patch.object(CustomTokenObtainPairView, 'get_serializer', return_value=serializer):
			response = CustomTokenObtainPairView.as_view()(request)

		self.assertEqual(response.status_code, 401)

	def test_refresh_view_rejects_invalid_refresh_token(self):
		request = self.factory.post(
			reverse('token-refresh'),
			{'refresh': 'not-a-token'},
			format='json'
		)

		serializer = MagicMock()
		serializer.is_valid.side_effect = ValidationError({'refresh': ['Token is invalid or expired.']})

		with patch.object(TokenRefreshView, 'get_serializer', return_value=serializer):
			response = TokenRefreshView.as_view()(request)

		self.assertEqual(response.status_code, 400)

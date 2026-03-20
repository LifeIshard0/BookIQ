from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import RegisterSerializer, UserProfileSerializer
from .models import User

from drf_spectacular.utils import extend_schema, OpenApiResponse


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims to JWT payload
        token['role'] = user.role
        token['username'] = user.username
        return token


@extend_schema(
    tags=['auth'],
    summary='Login and obtain JWT tokens',
    description=(
        'Authenticates credentials and returns access + refresh tokens. '
        'Access token expires in 60 minutes. '
        'Refresh token expires in 7 days.'
    ),
    responses={
        200: OpenApiResponse(description='Access and refresh tokens with role claim'),
        401: OpenApiResponse(description='Invalid credentials'),
    },
)
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


@extend_schema(
    tags=['auth'],
    summary='Register a new user',
    description='Creates a new user account. Default role is reader.',
    responses={
        201: OpenApiResponse(description='User created with JWT tokens'),
        400: OpenApiResponse(description='Validation error (duplicate email/username, password mismatch)'),
    },
)
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer


@extend_schema(
    tags=['auth'],
    summary='Get or update user profile',
    responses={200: OpenApiResponse(description='User profile data')},
)
class ProfileView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = UserProfileSerializer

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

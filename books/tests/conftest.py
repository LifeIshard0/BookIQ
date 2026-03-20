"""
conftest.py
===========
Shared pytest fixtures for the BookIQ test suite.

Fixtures:
  api_client          — unauthenticated DRF test client
  admin_user          — User with role='admin'
  curator_user        — User with role='curator'
  reader_user         — User with role='reader'
  admin_token         — JWT access token for admin_user
  curator_token       — JWT access token for curator_user
  reader_token        — JWT access token for reader_user
  auth_client_admin   — DRF client pre-authed as admin
  auth_client_curator — DRF client pre-authed as curator
  auth_client_reader  — DRF client pre-authed as reader
  sample_book         — A single Book object in the DB
  five_books          — 5 Book objects across different genres
  sample_csv          — In-memory CSV file for import tests
"""

import pytest
import uuid
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from books.models import Book, BookRating

User = get_user_model()


# ─── Helpers ───────────────────────────────────────────

def get_jwt_token(user) -> str:
    """Returns a valid JWT access token string for the given user."""
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


def make_client(user=None) -> APIClient:
    """Returns an APIClient, optionally pre-authenticated."""
    client = APIClient()
    if user:
        token = get_jwt_token(user)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


# ─── User fixtures ─────────────────────────────────────

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username='test_admin',
        email='admin@bookiq.test',
        password='AdminPass123!',
        role='admin',
    )


@pytest.fixture
def curator_user(db):
    return User.objects.create_user(
        username='test_curator',
        email='curator@bookiq.test',
        password='CuratorPass123!',
        role='curator',
    )


@pytest.fixture
def reader_user(db):
    return User.objects.create_user(
        username='test_reader',
        email='reader@bookiq.test',
        password='ReaderPass123!',
        role='reader',
    )


# ─── Auth client fixtures ──────────────────────────────

@pytest.fixture
def admin_token(admin_user):
    return get_jwt_token(admin_user)


@pytest.fixture
def curator_token(curator_user):
    return get_jwt_token(curator_user)


@pytest.fixture
def reader_token(reader_user):
    return get_jwt_token(reader_user)


@pytest.fixture
def auth_client_admin(admin_user):
    return make_client(admin_user)


@pytest.fixture
def auth_client_curator(curator_user):
    return make_client(curator_user)


@pytest.fixture
def auth_client_reader(reader_user):
    return make_client(reader_user)


# ─── Book fixtures ─────────────────────────────────────

@pytest.fixture
def sample_book(db, admin_user):
    """A single valid book created by admin."""
    return Book.objects.create(
        title='The Great Gatsby',
        normalized_title='The Great Gatsby',
        author='F. Scott Fitzgerald',
        normalized_author='Fitzgerald, F. Scott',
        isbn_13='9780743273565',
        genre='Fiction',
        description='A novel about the American dream set in the Jazz Age.',
        published_year=1925,
        publisher='Scribner',
        page_count=180,
        language='en',
        quality_score=0.85,
        is_flagged=False,
        created_by=admin_user,
    )


@pytest.fixture
def five_books(db, admin_user):
    """Five books across different genres for search/filter tests."""
    books_data = [
        {
            'title': 'Dune',
            'normalized_title': 'Dune',
            'author': 'Frank Herbert',
            'normalized_author': 'Herbert, Frank',
            'isbn_13': '9780441013593',
            'genre': 'Science Fiction',
            'description': 'Epic science fiction about desert planet Arrakis and spice.',
            'published_year': 1965,
            'quality_score': 0.90,
        },
        {
            'title': 'The Hobbit',
            'normalized_title': 'The Hobbit',
            'author': 'J.R.R. Tolkien',
            'normalized_author': 'Tolkien, J.R.R.',
            'isbn_13': '9780547928227',
            'genre': 'Fantasy',
            'description': 'A hobbit goes on an unexpected adventure with dwarves.',
            'published_year': 1937,
            'quality_score': 0.88,
        },
        {
            'title': 'Sapiens',
            'normalized_title': 'Sapiens',
            'author': 'Yuval Noah Harari',
            'normalized_author': 'Harari, Yuval Noah',
            'isbn_13': '9780062316110',
            'genre': 'History',
            'description': 'A brief history of humankind from ancient to modern times.',
            'published_year': 2011,
            'quality_score': 0.82,
        },
        {
            'title': 'The Girl with the Dragon Tattoo',
            'normalized_title': 'The Girl with the Dragon Tattoo',
            'author': 'Stieg Larsson',
            'normalized_author': 'Larsson, Stieg',
            'isbn_13': '9780307949486',
            'genre': 'Mystery',
            'description': 'A journalist and hacker investigate a family mystery in Sweden.',
            'published_year': 2005,
            'quality_score': 0.79,
        },
        {
            'title': 'Atomic Habits',
            'normalized_title': 'Atomic Habits',
            'author': 'James Clear',
            'normalized_author': 'Clear, James',
            'isbn_13': '9780735211292',
            'genre': 'Self-Help',
            'description': 'How tiny changes in habits lead to remarkable results.',
            'published_year': 2018,
            'quality_score': 0.91,
        },
    ]
    books = []
    for data in books_data:
        book = Book.objects.create(
            created_by=admin_user,
            language='en',
            **data
        )
        books.append(book)
    return books


@pytest.fixture
def sample_csv():
    """Returns a valid CSV bytes object for import testing."""
    content = (
        'isbn_13,title,authors,genre,description,published_year,page_count\n'
        '9780000000001,Test Book Alpha,Smith John,Fiction,'
        'A test book about testing.,2020,300\n'
        '9780000000002,Test Book Beta,Jones Jane,Mystery,'
        'A mystery test book.,2021,250\n'
        '9780000000003,Test Book Gamma,Brown Bob,History,'
        'A historical test book.,2019,400\n'
    )
    return content.encode('utf-8')


@pytest.fixture
def malformed_csv():
    """Returns a CSV with missing required columns."""
    content = 'not_isbn,not_title\ngarbage,data\n'
    return content.encode('utf-8')

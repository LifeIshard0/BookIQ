# BookIQ 📚

A data-driven RESTful book metadata intelligence platform built with Django REST Framework and PostgreSQL.

BookIQ provides full CRUD, PostgreSQL full-text search with GIN indexing, hybrid Reciprocal Rank Fusion search, content-based and collaborative filtering recommendations, genre trend analytics, and an MCP server layer for AI agent integration.

**Live URL:** [https://web-production-bca62.up.railway.app/api/docs/](https://web-production-bca62.up.railway.app/api/docs/)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [API Endpoints](#api-endpoints)
- [Error Envelope](#error-envelope)
- [Setup — Local Development](#setup--local-development)
- [Running Tests](#running-tests)
- [Data Import](#data-import)
- [Dataset](#dataset)
- [MCP Server](#mcp-server)
- [Deployment](#deployment)
- [Cleaning Pipeline](#cleaning-pipeline)
- [Search Implementation](#search-implementation)
- [Licence](#licence)

---

## Features

- **JWT Authentication** with role-based access control (reader → curator → admin)
- **Book CRUD** with a 7-step automated cleaning pipeline on every write
- **PostgreSQL Full-Text Search** using `SearchVector`, `SearchRank`, and GIN indexes with websearch syntax support
- **Hybrid Search** using Reciprocal Rank Fusion — blends FTS relevance with Wilson Score popularity
- **Personalised Recommendations** — three-strategy waterfall: content-based → collaborative filtering → Wilson Score cold-start
- **Genre Trend Analytics** — per-genre, per-month rating trends via `TruncMonth` aggregation
- **Catalogue Health Summary** — quality bands, flagged book stats, import history
- **Bulk CSV Import** — multi-step pipeline: parse → clean → deduplicate → persist, with per-row error tracking
- **MCP Server** — exposes BookIQ as a Model Context Protocol server for AI agent integration
- **Swagger UI** — interactive OpenAPI 3.0 documentation at `/api/docs/`
- **Consistent JSON error envelope** — every error returns `{error, status_code, detail}`

---

## Architecture

<img width="2160" height="1129" alt="image" src="https://github.com/user-attachments/assets/8ece68ba-34ce-4b4b-958d-0f3c8ca65c38" />

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 4.2, Django REST Framework 3.15 |
| Database | PostgreSQL 15 |
| Authentication | JWT via `djangorestframework-simplejwt` |
| Search | PostgreSQL `SearchVector` + `SearchRank`, GIN index |
| Task scheduling | Django management commands (sync) |
| API documentation | `drf-spectacular` (OpenAPI 3.0, Swagger UI) |
| Testing | pytest, pytest-django, pytest-cov |
| Production server | Railway |
| MCP integration | Anthropic MCP Python SDK |

---

## API Endpoints

### Authentication

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `POST` | `/api/auth/register/` | Public | Register new user (default role: reader) |
| `POST` | `/api/auth/login/` | Public | Login — returns JWT access + refresh tokens |
| `POST` | `/api/auth/token/refresh/` | Public | Exchange refresh token for new access token |
| `GET/PATCH` | `/api/auth/profile/` | Reader+ | Get or update own profile |

### Books

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/books/` | Public | List all books (paginated) |
| `POST` | `/api/books/` | Curator+ | Create a book — triggers 7-step cleaning pipeline |
| `GET` | `/api/books/{id}/` | Public | Retrieve a single book by UUID |
| `PATCH` | `/api/books/{id}/` | Curator+ | Partial update |
| `DELETE` | `/api/books/{id}/` | Admin | Delete a book |

### Search

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/books/search/` | Public | FTS with `SearchVector` + `SearchRank` + GIN index |
| `GET` | `/api/books/hybrid-search/` | Public | Hybrid RRF: FTS + Wilson Score blended ranking |

**Search query params:** `q`, `genre`, `author`, `min_quality`, `max_quality`, `min_rating`, `published_after`, `published_before`, `is_flagged`, `ordering`, `page`, `page_size`

**Hybrid search params:** `q` (required), `fts_weight` (default 0.7), `popularity_weight` (default 0.3), `page`, `page_size`

### Ratings

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `POST` | `/api/books/{id}/rate/` | Reader+ | Rate a book 1–5 (upsert) |
| `GET` | `/api/books/{id}/ratings/` | Public | List all ratings for a book |
| `GET` | `/api/books/{id}/my-rating/` | Reader+ | Get own rating for a book |

### User Ratings

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/ratings/` | Reader+ | List the authenticated user's ratings |
| `GET` | `/api/ratings/{id}/` | Reader+ | Retrieve one of the authenticated user's ratings |
| `PATCH` | `/api/ratings/{id}/` | Reader+ | Update one of the authenticated user's ratings |
| `DELETE` | `/api/ratings/{id}/` | Reader+ | Delete one of the authenticated user's ratings |

### Recommendations

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/books/recommendations/` | Reader+ | Personalised recommendations |

**Recommendation params:** `limit` (default 20), `strategy` (`content_based` \| `collaborative` \| `popularity`)

**Strategy waterfall:**
1. `content_based` — genre/author profile from books rated ≥ 4
2. `collaborative` — Jaccard similarity with users who liked the same books
3. `popularity_wilson_score` — Wilson Score cold-start fallback

### Imports

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `POST` | `/api/imports/` | Admin | Upload CSV — triggers full cleaning pipeline |
| `GET` | `/api/imports/` | Admin | List all import jobs |
| `GET` | `/api/imports/{id}/` | Admin | Get import job status and stats |

**CSV required columns:** `isbn_13`, `title`, `authors`, `genre`, `description`, `published_year`, `page_count`

### Analytics

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/analytics/genre-trends/` | Admin | Per-genre, per-month rating trends |
| `GET` | `/api/analytics/genre-quality/` | Admin | Genres ranked by avg metadata quality |
| `GET` | `/api/analytics/summary/` | Admin | Full catalogue health snapshot |

### Documentation

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/docs/` | Public | Swagger UI |
| `GET` | `/api/redoc/` | Public | ReDoc |
| `GET` | `/api/schema/` | Public | Raw OpenAPI 3.0 JSON |
| `GET` | `/health/` | Public | Health check |

---

## Error Envelope

Every error response — across all endpoints — returns a consistent JSON structure:

```json
{
  "error": true,
  "status_code": 404,
  "detail": "No Book matches the given query."
}
```

Validation errors return `detail` as a dict with field-level messages:

```json
{
  "error": true,
  "status_code": 400,
  "detail": {
    "rating": ["Ensure this value is less than or equal to 5."]
  }
}
```

---

## Setup — Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ running locally
- Git

### 1. Clone and install

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/bookiq.git
cd bookiq
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create PostgreSQL database

```bash
psql -U postgres
CREATE DATABASE bookiq;
CREATE USER bookiq_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE bookiq TO bookiq_user;
\q
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
DJANGO_SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://bookiq_user:yourpassword@localhost:5432/bookiq
DEBUG=True
```

### 4. Run migrations and import data

```bash
python manage.py migrate
python manage.py import_books data/books.csv --username=admin
```

### 5. Create an admin user

```bash
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
User.objects.create_superuser(
    username='admin',
    email='admin@bookiq.local',
    password='AdminPass123!',
    role='admin'
)
print('Admin created.')
"
```

### 6. Run the development server

```bash
python manage.py runserver
```

Open: [http://127.0.0.1:8000/api/docs/](http://127.0.0.1:8000/api/docs/)

---

## Running Tests

```bash
# Full suite
pytest books/tests/ -v

# With coverage report
pytest books/tests/ -v --cov=books --cov=users --cov-report=term-missing

# Single module
pytest books/tests/test_auth.py -v
pytest books/tests/test_books.py -v
pytest books/tests/test_imports.py -v
pytest books/tests/test_search.py -v
```

### Test coverage

| Module | Tests | Coverage areas |
|---|---:|---|
| `test_analytics.py` | 6 | Catalogue summary, genre trends, genre quality, admin access |
| `test_auth.py` | 9 | Registration, login, token refresh, profile |
| `test_books.py` | 13 | CRUD, RBAC (reader/curator/admin), rating upsert |
| `test_cleaning.py` | 15 | Title/author normalisation, ISBN validation, genre inference, duplicate detection, quality scoring |
| `test_exceptions.py` | 19 | JSON error envelope, custom handlers, DRF exception formatting |
| `test_filters.py` | 2 | BookFilter query behavior |
| `test_imports.py` | 17 | CSV upload, importer helpers, duplicate handling, RBAC |
| `test_mcp_server.py` | 6 | MCP server tools and resources |
| `test_models.py` | 8 | Model fields, constraints, signals, aggregates |
| `test_permissions.py` | 4 | Role-based permission classes |
| `test_recommender.py` | 6 | Recommendation waterfall and strategies |
| `test_search.py` | 25 | FTS, hybrid RRF, filters, pagination |
| `test_serializers.py` | 8 | Book, rating, and import-job serialization |
| `test_service_logic.py` | 28 | Search, analytics, recommendation, and helper logic |
| `test_view_helpers.py` | 8 | Shared view helpers and response shaping |

`books/tests/conftest.py` and `books/tests/__init__.py` are support files, not test modules.

Total test functions across the test modules above: 168.

---

## Data Import

BookIQ accepts CSV files via the import endpoint and the `import_books` management command.

Command-line import:

```bash
python manage.py import_books data/books.csv --username=admin
```

The importer accepts these CSV column names and aliases:

| CSV column | Maps to | Notes |
|---|---|---|
| `title` | `title` | Required |
| `authors` / `author` | `author` | Required |
| `isbn_13` / `isbn13` / `isbn` | `isbn_13` | Optional, validated when present |
| `description` | `description` | Optional |
| `genre` / `categories` | `genre` | Optional |
| `published_year` | `published_year` | Optional |
| `page_count` / `num_pages` | `page_count` | Optional |
| `publisher` | `publisher` | Optional |
| `thumbnail` / `cover_url` | `cover_url` | Optional |
| `language` | `language` | Optional |

The import pipeline processes each row through:

1. Parse — validate CSV structure and required columns.
2. Clean — normalise title casing, author name (Surname, First), strip whitespace.
3. Validate ISBN — check ISBN-13 check digit.
4. Infer genre — fill missing genres from description keywords.
5. Detect duplicates — skip exact ISBN duplicates and reduce quality for likely fuzzy duplicates.
6. Quality score — compute a weighted score from completeness, ISBN validity, and genre confidence.
7. Flag — mark books with quality score < 0.8 for curator review.
8. Persist — bulk insert valid rows.

The quality score is weighted as follows:

```text
quality_score = 0.5 * completeness + 0.3 * isbn_validity + 0.2 * genre_confidence
```

```bash
# Via API (requires admin token)
curl -X POST https://web-production-bca62.up.railway.app/api/imports/ \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -F "file=@books.csv"
```

---

## Dataset

Dataset: 7k Books with Metadata (Kaggle / [dylanjcastillo](https://www.kaggle.com/datasets/dylanjcastillo/7k-books-with-metadata?resource=download))

---

## MCP Server

BookIQ includes an MCP (Model Context Protocol) server that exposes the API to AI agents such as Claude Desktop, Cursor, and AutoGen.

```bash
pip install mcp httpx
python bookiq_mcp_server.py
```

### Available tools

| Tool | Description |
|---|---|
| `search_books` | Full-text search with filters |
| `hybrid_search_books` | RRF blended search |
| `get_book` | Retrieve book by UUID |
| `get_recommendations` | Personalised recommendations |
| `get_genre_trends` | Genre rating trends (admin) |
| `rate_book` | Rate a book 1–5 (upsert) |

### Available resources

| URI | Description |
|---|---|
| `books://catalogue/summary` | Live catalogue health snapshot |
| `books://trending` | Top 20 books by Wilson Score |

### Claude Desktop setup

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bookiq": {
      "command": "python",
      "args": ["/absolute/path/to/bookiq/bookiq_mcp_server.py"],
      "env": {
        "BOOKIQ_BASE_URL": "http://127.0.0.1:8000",
        "BOOKIQ_API_TOKEN": "your_jwt_access_token"
      }
    }
  }
}
```

Start Django locally, then restart Claude Desktop. BookIQ tools will appear automatically.

---

## Deployment

Live URL: [https://web-production-bca62.up.railway.app/](https://web-production-bca62.up.railway.app/)

Deployed on **Railway** with PostgreSQL.

### Re-deploy after changes

If the GitHub repository is connected to Railway, every push to the tracked branch triggers a new deployment automatically.

```bash
git add .
git commit -m "your commit message"
git push origin main
```

You can also trigger a manual redeploy from the Railway dashboard.

### Environment variables

Set these in the Railway project or service variables dashboard:

| Variable | Description |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key (50+ chars) |
| `DJANGO_SETTINGS_MODULE` | `bookiq.settings_production` |
| `DATABASE_URL` | PostgreSQL connection string |
| `ALLOWED_HOSTS` | `web-production-bca62.up.railway.app` |
| `DEBUG` | `False` |

### Public URL

Railway provides a generated public domain for deployed services, and you can also attach a custom domain if needed.

---

## Cleaning Pipeline

Every book written to the database passes through a 7-step automated cleaning pipeline (`books/services/cleaning.py`):

| Step | Operation |
|---:|---|
| 1 | Normalise title casing (title case, strip whitespace) |
| 2 | Normalise author name to Surname, First format |
| 3 | Validate and normalise ISBN-13 (check digit verification) |
| 4 | Infer genre from description keywords when no genre is supplied |
| 5 | Detect likely duplicates with fuzzy title/author matching |
| 6 | Compute quality score from completeness, ISBN validity, and genre confidence |
| 7 | Set `is_flagged = True` if quality score < 0.8 |

Likely duplicates are not rejected outright; instead, the quality score is reduced so they are more likely to be flagged for review.

---

## Search Implementation

### Full-Text Search

Uses PostgreSQL `SearchVector` (weighted: title A, author B, description C) stored as a computed column and indexed with a GIN index. Queries use `SearchRank` for relevance scoring and `websearch_to_tsquery` for websearch syntax support (`"exact phrase"`, `OR`, `-exclusion`).

### Hybrid Reciprocal Rank Fusion

Combines two ranking signals using RRF (Cormack et al., 2009):

```text
rrf_score = fts_weight * (1 / (k + fts_rank))
          + pop_weight * (1 / (k + pop_rank))
```

Where `k = 60` (standard RRF constant) and `pop_rank` is derived from Wilson Score Lower Bound — a statistically conservative popularity estimate that penalises books with few ratings.

---

## Licence

MIT

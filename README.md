# BookIQ 📚

A data-driven RESTful book metadata intelligence platform built with **Django REST Framework** and **PostgreSQL**.

BookIQ provides full CRUD, PostgreSQL full-text search with GIN indexing, hybrid Reciprocal Rank Fusion search, content-based and collaborative filtering recommendations, genre trend analytics, bulk CSV import, and an MCP server layer for AI agent integration.

## Links

- **GitHub Repository:** https://github.com/jasontsoi/bookiq
- **Live API / Swagger UI:** https://web-production-bca62.up.railway.app/api/docs/
- **Live API Base URL:** https://web-production-bca62.up.railway.app/
- **Presentation Slides:** https://canva.link/801336kr41cz26c
- **Technical Report (PDF):** `docs/BookIQ-Technical-Report.pdf`
- **API Documentation (PDF):** `docs/API-Documentation.pdf`

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Data Model](#data-model)
- [Role-Based Access Control](#role-based-access-control)
- [API Endpoints](#api-endpoints)
- [Error Envelope](#error-envelope)
- [Setup — Local Development](#setup--local-development)
- [Running Tests](#running-tests)
- [Data Import](#data-import)
- [Search and Ranking](#search-and-ranking)
- [Recommendations](#recommendations)
- [Analytics](#analytics)
- [MCP Server](#mcp-server)
- [Deployment](#deployment)
- [Dataset](#dataset)
- [GenAI Usage](#genai-usage)
- [Licence](#licence)

---

## Overview

BookIQ is a production-grade RESTful API for book metadata management and discovery. It was designed as a data-driven platform rather than a simple catalogue service, combining CRUD operations with automated metadata cleaning, relevance-ranked search, recommendation pipelines, analytics, and deployment-ready API documentation.

The motivation behind BookIQ is that many public book APIs return raw metadata with little validation or intelligence. BookIQ improves this by automatically cleaning book records, validating ISBN-13 values, inferring missing genres, detecting likely duplicates, scoring metadata quality, and exposing curator/admin workflows for catalogue health.

### Key project metrics

- 168 automated tests across 15 test modules
- 6,400+ books imported from a Kaggle dataset
- Full CRUD with JWT authentication and RBAC
- PostgreSQL full-text search with GIN indexing
- Hybrid RRF search with Wilson Score popularity blending
- Three-strategy recommendation waterfall
- MCP-compatible server for AI agent integration
- Railway deployment with PostgreSQL and CI/CD

---

## Key Features

- **JWT Authentication** with role-based access control (`reader` → `curator` → `admin`)
- **Book CRUD** with an automated cleaning pipeline on every write
- **PostgreSQL Full-Text Search** using `SearchVector`, `SearchRank`, and GIN indexes
- **Hybrid Search** using Reciprocal Rank Fusion (RRF)
- **Personalised Recommendations** using content-based, collaborative, and popularity fallback strategies
- **Genre Trend Analytics** using monthly aggregation
- **Catalogue Health Summary** for metadata quality monitoring
- **Bulk CSV Import** with per-row validation and error tracking
- **MCP Server Layer** for AI agent interoperability
- **Swagger UI** and OpenAPI 3.0 documentation
- **Consistent JSON Error Envelope** across endpoints

---

## Architecture

BookIQ follows Django’s MVT structure with a dedicated service layer to keep business logic out of views.

```text
HTTP Request
    ↓
DRF ViewSet (routing, auth, permissions)
    ↓
Service Layer (cleaning.py, search.py, recommender.py, analytics.py, importer.py)
    ↓
Models + ORM
    ↓
PostgreSQL
    ↓
JSON Response
```

```text
COMP3011-Web-Services-and-Web-Data-CW1/
├── bookiq/
│   ├── __init__.py
│   ├── asgi.py                # ASGI application entrypoint
│   ├── settings.py            # Base Django settings
│   ├── settings_production.py # Production-only Django settings
│   ├── urls.py                # Project-level URL routing
│   └── wsgi.py                # WSGI application entrypoint
├── books/
│   ├── __init__.py
│   ├── admin.py               # Django admin registrations
│   ├── apps.py                # App configuration
│   ├── exceptions.py          # Custom exception handling
│   ├── filters.py             # Query filter definitions
│   ├── models.py              # Core data models
│   ├── pagination.py          # Pagination classes
│   ├── permissions.py         # Role-based access control
│   ├── serializers.py         # Validation and JSON serialization
│   ├── urls.py                # Book-related API routes
│   ├── urls_analytics.py      # Analytics API routes
│   ├── views.py               # Main API views
│   ├── views_analytics.py     # Analytics views
│   ├── management/
│   │   └── commands/
│   │       ├── build_search_index.py # Command to build search index
│   │       └── import_books.py       # CSV import command
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   ├── 0002_remove_embedding_field.py
│   │   └── 0003_add_search_vector_gin_index.py
│   ├── services/
│   │   ├── analytics.py       # Analytics/business logic
│   │   ├── cleaning.py        # Metadata cleaning pipeline
│   │   ├── importer.py        # Import pipeline logic
│   │   ├── recommender.py     # Recommendation engine
│   │   └── search.py          # Full-text and hybrid search logic
│   └── tests/
│       ├── test_analytics.py
│       ├── test_auth.py
│       ├── test_books.py
│       ├── test_cleaning.py
│       ├── test_exceptions.py
│       ├── test_filters.py
│       ├── test_imports.py
│       ├── test_mcp_server.py
│       ├── test_models.py
│       ├── test_permissions.py
│       ├── test_recommender.py
│       ├── test_search.py
│       ├── test_serializers.py
│       ├── test_service_logic.py
│       └── test_view_helpers.py
├── users/
│   ├── __init__.py
│   ├── admin.py               # User admin configuration
│   ├── apps.py                # App configuration
│   ├── models.py              # Custom user model
│   ├── serializers.py         # User auth/profile serializers
│   ├── tests.py               # User-related tests
│   ├── urls.py                # User/auth routes
│   ├── views.py               # Register/login/profile views
│   └── migrations/
│       └── 0001_initial.py
├── data/
│   ├── README.md              # Dataset documentation
│   └── books.csv              # Source dataset
├── docs/
│   ├── schema.json            # OpenAPI JSON schema
│   └── schema.yml             # OpenAPI YAML schema
├── bookiq_mcp_server.py       # MCP-compatible server layer
├── manage.py                  # Django management entrypoint
├── Procfile                   # Deployment process definition
├── pytest.ini                 # Pytest configuration
├── railway.toml               # Railway deployment config
├── README.md                  # Project overview and usage
├── requirements.txt           # Python dependencies
└── schema.yml                 # Generated API schema
```

### Design principles

- **Separation of concerns** — views handle HTTP, services handle logic, models handle persistence
- **Testability** — service functions are unit-tested independently of request/response logic
- **Reusability** — the same service logic is used by REST endpoints, management commands, and the MCP server
- **Maintainability** — business rules are centralised in `books/services/`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 4.2, Django REST Framework 3.15 |
| Database | PostgreSQL 15 |
| Authentication | JWT via `djangorestframework-simplejwt` |
| Search | PostgreSQL `SearchVector`, `SearchRank`, GIN index |
| Import / jobs | Django management commands |
| API docs | `drf-spectacular` (OpenAPI 3.0, Swagger UI) |
| Testing | `pytest`, `pytest-django`, `pytest-cov` |
| Deployment | Railway |
| MCP integration | Python MCP SDK |

### Why this stack?

- **Python** was chosen for its strong string-processing and data-handling ecosystem.
- **Django REST Framework** provided mature authentication, serializers, permission classes, and routing.
- **PostgreSQL** was selected over SQLite because it supports native full-text search, GIN indexes, JSON fields, and stronger production-grade relational features.
- **Railway** was used for simple GitHub-connected deployment with managed PostgreSQL.

### Framework trade-off

| Criterion | Django + DRF | FastAPI | Flask | Node.js/Express |
|---|---|---|---|---|
| Built-in ORM | ✅ | ❌ | ❌ | ❌ |
| Built-in auth ecosystem | ✅ | ❌ | ❌ | ❌ |
| Admin panel | ✅ | ❌ | ❌ | ❌ |
| Permission model | ✅ | 🟡 | ❌ | 🟡 |
| PostgreSQL integration | ✅ | 🟡 | 🟡 | 🟡 |
| Chosen for BookIQ | ✅ | ❌ | ❌ | ❌ |

Django has a larger baseline memory footprint than FastAPI, but that trade-off was acceptable for a synchronous, database-heavy coursework API.

---

## Data Model

BookIQ is built around three core models:

### `Book`

Stores both raw metadata and cleaned intelligence fields.

Key fields:
- `id` — UUID primary key
- `isbn_13` — unique ISBN-13
- `title`, `author`, `description`, `genre`, `published_year`, `publisher`, `page_count`
- `normalized_title`, `normalized_author`
- `quality_score`
- `genre_confidence`
- `is_flagged`
- `average_rating`, `rating_count`, `upvote_count`, `downvote_count`
- `created_by`

### `BookRating`

Stores a user’s 1–5 rating for a book.

Key features:
- One rating per user per book
- Upsert behaviour on rating endpoint
- Aggregates pushed back onto `Book` via Django signals

### `ImportJob`

Tracks CSV import runs.

Key fields:
- `status`
- `total_rows`
- `cleaned_count`
- `duplicate_count`
- `failed_count`
- `error_log`

---

## Role-Based Access Control

Three roles are defined on the custom `User` model:

| Role | Capabilities |
|---|---|
| `reader` | Browse books, rate books, get recommendations |
| `curator` | Reader permissions + create and update books |
| `admin` | Curator permissions + delete books, run imports, access analytics |

Permission checks are enforced server-side through custom DRF permission classes, with role evaluation performed from the database-backed user model rather than trusting the JWT claim alone.

---

## API Endpoints

### Authentication

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `POST` | `/api/auth/register/` | Public | Register new user |
| `POST` | `/api/auth/login/` | Public | Login and receive JWT tokens |
| `POST` | `/api/auth/token/refresh/` | Public | Refresh access token |
| `GET/PATCH` | `/api/auth/profile/` | Reader+ | Get or update own profile |

### Books

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/books/` | Public | List all books |
| `POST` | `/api/books/` | Curator+ | Create a book |
| `GET` | `/api/books/{id}/` | Public | Retrieve one book |
| `PATCH` | `/api/books/{id}/` | Curator+ | Update a book |
| `DELETE` | `/api/books/{id}/` | Admin | Delete a book |

### Search

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/books/search/` | Public | Full-text search with filters |
| `GET` | `/api/books/hybrid-search/` | Public | Hybrid RRF search |

**Search params:** `q`, `genre`, `author`, `min_quality`, `max_quality`, `min_rating`, `published_after`, `published_before`, `is_flagged`, `ordering`, `page`, `page_size`

**Hybrid search params:** `q`, `fts_weight`, `popularity_weight`, `page`, `page_size`

### Ratings

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `POST` | `/api/books/{id}/rate/` | Reader+ | Rate a book 1–5 (upsert) |
| `GET` | `/api/books/{id}/ratings/` | Public | List ratings for a book |
| `GET` | `/api/books/{id}/my-rating/` | Reader+ | Get own rating for a book |

### User Ratings

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/ratings/` | Reader+ | List own ratings |
| `GET` | `/api/ratings/{id}/` | Reader+ | Retrieve one own rating |
| `PATCH` | `/api/ratings/{id}/` | Reader+ | Update one own rating |
| `DELETE` | `/api/ratings/{id}/` | Reader+ | Delete one own rating |

### Recommendations

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/books/recommendations/` | Reader+ | Personalised recommendations |

**Recommendation params:** `limit`, `strategy`

### Imports

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `POST` | `/api/imports/` | Admin | Upload CSV import |
| `GET` | `/api/imports/` | Admin | List import jobs |
| `GET` | `/api/imports/{id}/` | Admin | Retrieve import job |

### Analytics

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/analytics/genre-trends/` | Admin | Monthly genre trends |
| `GET` | `/api/analytics/genre-quality/` | Admin | Genre quality rankings |
| `GET` | `/api/analytics/summary/` | Admin | Catalogue health summary |

### Documentation

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/docs/` | Public | Swagger UI |
| `GET` | `/api/redoc/` | Public | ReDoc |
| `GET` | `/api/schema/` | Public | OpenAPI schema |
| `GET` | `/health/` | Public | Health check |

---

## Error Envelope

Every API error returns a consistent JSON structure:

```json
{
  "error": true,
  "status_code": 404,
  "detail": "No Book matches the given query."
}
```

Validation errors return `detail` as a field-level dictionary:

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
- PostgreSQL 15+
- Git

### 1. Clone and install

```bash
git clone https://github.com/jasontsoi/bookiq.git
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

Example `.env`:

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

### 6. Run the server

```bash
python manage.py runserver
```

Open: http://127.0.0.1:8000/api/docs/

---

## Running Tests

### Full suite

```bash
pytest books/tests/ -v
```

### With coverage

```bash
pytest books/tests/ -v --cov=books --cov=users --cov-report=term-missing
```

### Example single-module runs

```bash
pytest books/tests/test_auth.py -v
pytest books/tests/test_books.py -v
pytest books/tests/test_imports.py -v
pytest books/tests/test_search.py -v
```

### Coverage summary

| Module | Tests | Coverage areas |
|---|---:|---|
| `test_analytics.py` | 6 | Catalogue summary, genre trends, genre quality |
| `test_auth.py` | 9 | Registration, login, token refresh, profile |
| `test_books.py` | 13 | CRUD, RBAC, rating upsert |
| `test_cleaning.py` | 15 | Normalisation, ISBN validation, genre inference, duplicates, quality |
| `test_exceptions.py` | 19 | Error envelope and custom exception formatting |
| `test_filters.py` | 2 | Book filtering |
| `test_imports.py` | 17 | CSV upload, duplicate handling, RBAC |
| `test_mcp_server.py` | 6 | MCP tools and resources |
| `test_models.py` | 8 | Model constraints, signals, aggregates |
| `test_permissions.py` | 4 | Role-based permissions |
| `test_recommender.py` | 6 | Recommendation strategies |
| `test_search.py` | 25 | FTS, hybrid RRF, filters, pagination |
| `test_serializers.py` | 8 | Serialisation |
| `test_service_logic.py` | 28 | Service-layer logic |
| `test_view_helpers.py` | 8 | Shared view helper behaviour |

**Total test functions:** 168

---

## Data Import

BookIQ supports CSV import through both the API and a management command.

### Command-line import

```bash
python manage.py import_books data/books.csv --username=admin
```

### Accepted CSV columns

| CSV column | Maps to | Notes |
|---|---|---|
| `title` | `title` | Required |
| `authors` / `author` | `author` | Required |
| `isbn_13` / `isbn13` / `isbn` | `isbn_13` | Optional |
| `description` | `description` | Optional |
| `genre` / `categories` | `genre` | Optional |
| `published_year` | `published_year` | Optional |
| `page_count` / `num_pages` | `page_count` | Optional |
| `publisher` | `publisher` | Optional |
| `thumbnail` / `cover_url` | `cover_url` | Optional |
| `language` | `language` | Optional |

### Import pipeline

1. Parse CSV structure
2. Clean and normalise fields
3. Validate ISBN-13
4. Infer missing genre
5. Detect duplicates
6. Compute quality score
7. Flag low-quality records
8. Persist valid rows

### API example

```bash
curl -X POST https://web-production-bca62.up.railway.app/api/imports/ \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -F "file=@books.csv"
```

---

## Search and Ranking

### Full-Text Search

BookIQ uses PostgreSQL full-text search with:

- Weighted `SearchVector`
- `SearchRank` scoring
- GIN index for fast retrieval
- `websearch_to_tsquery` syntax support

Weighted fields:
- `title` → A
- `author` → B
- `description` → C

This supports quoted phrases, `OR`, and exclusion syntax.

### Hybrid Reciprocal Rank Fusion

Hybrid search combines text relevance with popularity using RRF:

```text
rrf_score = fts_weight * (1 / (k + fts_rank))
          + pop_weight * (1 / (k + pop_rank))
```

Where:
- `k = 60`
- `pop_rank` is derived from Wilson Score Lower Bound
- Default weighting is text-heavy but popularity-aware

### Why Wilson Score?

Wilson Score is more conservative than raw average rating because it penalises books with very few ratings.

---

## Recommendations

BookIQ uses a three-strategy waterfall:

1. **Content-based filtering** — builds a user profile from highly rated books
2. **Collaborative filtering** — uses Jaccard similarity between users
3. **Popularity fallback** — uses Wilson Score for cold-start users

The recommendations endpoint includes a strategy label so results are explainable.

---

## Analytics

Admin-only analytics include:

- **Genre trends** — monthly average ratings per genre
- **Genre quality** — genres ranked by metadata quality
- **Catalogue summary** — total books, flagged counts, import history, quality overview

These endpoints support curator and admin oversight of data quality and reading trends.

---

## MCP Server

BookIQ includes an MCP server for AI-agent use.

### Run locally

```bash
pip install mcp httpx
python bookiq_mcp_server.py
```

### Available tools

| Tool | Description |
|---|---|
| `search_books` | Full-text search with filters |
| `hybrid_search_books` | Hybrid RRF search |
| `get_book` | Retrieve by UUID |
| `get_recommendations` | Personalised recommendations |
| `get_genre_trends` | Genre analytics |
| `rate_book` | Rate a book |

### Available resources

| URI | Description |
|---|---|
| `books://catalogue/summary` | Live catalogue health snapshot |
| `books://trending` | Top books by Wilson Score |

### Claude Desktop example

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

---

## Deployment

BookIQ is deployed on **Railway** with PostgreSQL.

### Live deployment

- https://web-production-bca62.up.railway.app/
- https://web-production-bca62.up.railway.app/api/docs/

### Redeploy after changes

```bash
git add .
git commit -m "your commit message"
git push origin main
```

If GitHub is connected to Railway, each push to the tracked branch triggers a redeploy automatically.

### Environment variables

| Variable | Description |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_SETTINGS_MODULE` | Production settings module |
| `DATABASE_URL` | PostgreSQL connection string |
| `ALLOWED_HOSTS` | Allowed hostnames |
| `DEBUG` | `False` in production |

---

## Dataset

BookIQ uses the **7k Books with Metadata** dataset from Kaggle:

https://www.kaggle.com/datasets/dylanjcastillo/7k-books-with-metadata

---

## BookIQ — Full Build Roadmap (March → May 2026)

🟥 Phase 1 — Foundation (Week 1–2, now)
- 01	Django project + app structure + requirements.txt
- 02	Custom User model with role field (Reader/Curator/Admin)
- 03	JWT authentication endpoints (register, login, refresh)
- 04	Book model + migrations
- 05	Book CRUD endpoints (full REST)
- 06	RBAC permission classes wired to endpoints

🟧 Phase 2 — Data & Intelligence (Week 3–)
- 07	BookRating model + rate endpoint (upsert + signals)
- 08	Metadata cleaning pipeline (7 steps)
- 09	CSV dataset import + ImportJob model
- 10	Keyword search endpoint
- 11	Semantic embeddings (sentence-transformers)
- 12	Hybrid search with RRF

🟨 Phase 3 — Advanced Features (Week 5–6)
- 13	Content-based recommender
- 14	Collaborative filtering + cold start fallback
- 15	Genre trend analytics (TruncMonth + Wilson Score)
- 16	Catalogue summary analytics endpoint

🟩 Phase 4 — Professional Polish (Week 7–8)
- 17	MCP server layer (bookiq_mcp_server.py)
- 18	Swagger UI / drf-spectacular API docs
- 19	Global error handling + consistent JSON envelope
- 20	pytest suite (4 test modules)

🟦 Phase 5 — Deployment & Submission (Week 9–10)
- 21	Production settings (DEBUG=False, env vars, whitenoise)
- 22	Railway deployment + PostgreSQL wired up
- 23	README.md (professional, full setup instructions)
- 24	Final polish — pagination, ordering, filtering
- 25	API docs PDF export + Notion report evidence filled in

## Licence

MIT

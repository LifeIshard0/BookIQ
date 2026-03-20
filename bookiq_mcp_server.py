"""
BookIQ MCP Server
=================
Exposes BookIQ as a Model Context Protocol (MCP) server.

Tools (actions an AI agent can invoke):
  search_books          — full-text search with filters
  get_book              — retrieve a single book by ID
  get_recommendations   — personalised recommendations (requires auth token)
  get_genre_trends      — genre rating trends over time (requires admin token)
  rate_book             — rate a book (requires auth token)

Resources (data an AI agent can read):
  books://catalogue/summary   — live catalogue health snapshot
  books://trending            — top books by Wilson Score

Usage:
  python bookiq_mcp_server.py

  Or via Claude Desktop — add to claude_desktop_config.json:
  {
    "mcpServers": {
      "bookiq": {
        "command": "python",
        "args": ["/absolute/path/to/bookiq_mcp_server.py"],
        "env": {
          "BOOKIQ_BASE_URL": "http://127.0.0.1:8000",
          "BOOKIQ_API_TOKEN": "your_jwt_token_here"
        }
      }
    }
  }
"""

import asyncio
import json
import os
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# --- Configuration ---
BASE_URL = os.environ.get('BOOKIQ_BASE_URL', 'http://127.0.0.1:8000')
API_TOKEN = os.environ.get('BOOKIQ_API_TOKEN', '')

server = Server('bookiq')


def get_headers() -> dict:
    """Returns auth headers if a token is configured."""
    headers = {'Content-Type': 'application/json'}
    if API_TOKEN:
        headers['Authorization'] = f'Bearer {API_TOKEN}'
    return headers


async def api_get(path: str, params: dict = None) -> dict:
    """Performs an authenticated GET request to the BookIQ REST API."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f'{BASE_URL}{path}',
            params=params or {},
            headers=get_headers(),
        )
        response.raise_for_status()
        return response.json()


async def api_post(path: str, body: dict = None) -> dict:
    """Performs an authenticated POST request to the BookIQ REST API."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f'{BASE_URL}{path}',
            json=body or {},
            headers=get_headers(),
        )
        response.raise_for_status()
        return response.json()


# ─────────────────────────────────────────────
# TOOLS — actions an AI agent can invoke
# ─────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name='search_books',
            description=(
                'Search the BookIQ catalogue using full-text search. '
                'Supports websearch syntax: "exact phrase", word1 OR word2, -exclusion. '
                'Returns ranked results with relevance scores and highlighted snippets.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'q': {
                        'type': 'string',
                        'description': 'Search query. Supports websearch syntax.'
                    },
                    'genre': {
                        'type': 'string',
                        'description': 'Filter by genre (partial match).'
                    },
                    'min_quality': {
                        'type': 'number',
                        'description': 'Minimum quality score (0.0–1.0).'
                    },
                    'min_rating': {
                        'type': 'number',
                        'description': 'Minimum average rating (1–5).'
                    },
                    'published_after': {
                        'type': 'integer',
                        'description': 'Published year from (e.g. 2000).'
                    },
                    'published_before': {
                        'type': 'integer',
                        'description': 'Published year to (e.g. 2020).'
                    },
                    'page_size': {
                        'type': 'integer',
                        'description': 'Results per page (default 10, max 50).',
                        'default': 10
                    },
                },
                'required': ['q'],
            },
        ),
        types.Tool(
            name='hybrid_search_books',
            description=(
                'Search BookIQ using hybrid Reciprocal Rank Fusion — blends '
                'PostgreSQL full-text relevance with Wilson Score popularity. '
                'Returns rrf_score, fts_rank, and wilson_score per result.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'q': {
                        'type': 'string',
                        'description': 'Search query.'
                    },
                    'fts_weight': {
                        'type': 'number',
                        'description': 'Weight for FTS relevance signal (0.0–1.0, default 0.7).',
                        'default': 0.7
                    },
                    'popularity_weight': {
                        'type': 'number',
                        'description': 'Weight for popularity signal (0.0–1.0, default 0.3).',
                        'default': 0.3
                    },
                    'page_size': {
                        'type': 'integer',
                        'description': 'Results per page (default 10).',
                        'default': 10
                    },
                },
                'required': ['q'],
            },
        ),
        types.Tool(
            name='get_book',
            description=(
                'Retrieve full details for a single book by its UUID. '
                'Returns all metadata including quality score, cleaning pipeline '
                'output, rating aggregates, and genre confidence.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'book_id': {
                        'type': 'string',
                        'description': 'UUID of the book to retrieve.'
                    },
                },
                'required': ['book_id'],
            },
        ),
        types.Tool(
            name='get_recommendations',
            description=(
                'Get personalised book recommendations for the authenticated user. '
                'Uses content-based filtering → collaborative filtering → '
                'Wilson Score popularity fallback. '
                'Requires BOOKIQ_API_TOKEN to be set.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'limit': {
                        'type': 'integer',
                        'description': 'Number of recommendations (default 10, max 50).',
                        'default': 10
                    },
                    'strategy': {
                        'type': 'string',
                        'enum': ['content_based', 'collaborative', 'popularity'],
                        'description': 'Force a specific recommendation strategy.'
                    },
                },
            },
        ),
        types.Tool(
            name='get_genre_trends',
            description=(
                'Get per-genre, per-month rating trends. '
                'Uses TruncMonth aggregation over the last N months. '
                'Requires admin JWT token in BOOKIQ_API_TOKEN.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'months': {
                        'type': 'integer',
                        'description': 'How many months to look back (default 12, max 24).',
                        'default': 12
                    },
                },
            },
        ),
        types.Tool(
            name='rate_book',
            description=(
                'Rate a book on a scale of 1–5. '
                'If you have already rated this book, your rating is updated (upsert). '
                'Requires BOOKIQ_API_TOKEN to be set.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'book_id': {
                        'type': 'string',
                        'description': 'UUID of the book to rate.'
                    },
                    'rating': {
                        'type': 'integer',
                        'description': 'Rating value (1–5).',
                        'minimum': 1,
                        'maximum': 5
                    },
                    'review': {
                        'type': 'string',
                        'description': 'Optional written review.'
                    },
                },
                'required': ['book_id', 'rating'],
            },
        ),
    ]


@server.call_tool()
async def call_tool(
    name: str,
    arguments: dict
) -> list[types.TextContent]:
    """
    Dispatches tool calls to the appropriate BookIQ REST endpoint.
    All errors are caught and returned as readable error messages
    rather than exceptions — AI agents handle text better than stack traces.
    """
    try:
        if name == 'search_books':
            params = {'q': arguments['q'], 'page_size': arguments.get('page_size', 10)}
            for key in ('genre', 'min_quality', 'min_rating',
                        'published_after', 'published_before'):
                if key in arguments:
                    params[key] = arguments[key]
            data = await api_get('/api/books/search/', params=params)
            return [types.TextContent(
                type='text',
                text=json.dumps(data, indent=2, default=str)
            )]

        elif name == 'hybrid_search_books':
            params = {
                'q': arguments['q'],
                'page_size': arguments.get('page_size', 10),
                'fts_weight': arguments.get('fts_weight', 0.7),
                'popularity_weight': arguments.get('popularity_weight', 0.3),
            }
            data = await api_get('/api/books/hybrid-search/', params=params)
            return [types.TextContent(
                type='text',
                text=json.dumps(data, indent=2, default=str)
            )]

        elif name == 'get_book':
            data = await api_get(f'/api/books/{arguments["book_id"]}/')
            return [types.TextContent(
                type='text',
                text=json.dumps(data, indent=2, default=str)
            )]

        elif name == 'get_recommendations':
            params = {'limit': arguments.get('limit', 10)}
            if 'strategy' in arguments:
                params['strategy'] = arguments['strategy']
            data = await api_get('/api/books/recommendations/', params=params)
            return [types.TextContent(
                type='text',
                text=json.dumps(data, indent=2, default=str)
            )]

        elif name == 'get_genre_trends':
            params = {'months': arguments.get('months', 12)}
            data = await api_get('/api/analytics/genre-trends/', params=params)
            return [types.TextContent(
                type='text',
                text=json.dumps(data, indent=2, default=str)
            )]

        elif name == 'rate_book':
            body = {
                'rating': arguments['rating'],
                'review': arguments.get('review', ''),
            }
            data = await api_post(
                f'/api/books/{arguments["book_id"]}/rate/',
                body=body
            )
            return [types.TextContent(
                type='text',
                text=json.dumps(data, indent=2, default=str)
            )]

        else:
            return [types.TextContent(
                type='text',
                text=f'Unknown tool: {name}'
            )]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(
            type='text',
            text=json.dumps({
                'error': True,
                'status_code': e.response.status_code,
                'detail': e.response.text,
                'tool': name,
            }, indent=2)
        )]
    except httpx.RequestError as e:
        return [types.TextContent(
            type='text',
            text=json.dumps({
                'error': True,
                'detail': f'Could not connect to BookIQ at {BASE_URL}. '
                          f'Is the server running? ({str(e)})',
                'tool': name,
            }, indent=2)
        )]
    except Exception as e:
        return [types.TextContent(
            type='text',
            text=json.dumps({
                'error': True,
                'detail': str(e),
                'tool': name,
            }, indent=2)
        )]


# ─────────────────────────────────────────────
# RESOURCES — data an AI agent can read
# ─────────────────────────────────────────────

@server.list_resources()
async def list_resources() -> list[types.Resource]:
    return [
        types.Resource(
            uri='books://catalogue/summary',
            name='Catalogue Summary',
            description=(
                'Live BookIQ catalogue health snapshot. '
                'Includes total books, flagged %, avg quality score, '
                'quality bands, genre distribution, and recent additions. '
                'Requires admin token.'
            ),
            mimeType='application/json',
        ),
        types.Resource(
            uri='books://trending',
            name='Trending Books',
            description=(
                'Top 20 books by Wilson Score Lower Bound. '
                'Statistically credible popularity ranking — '
                'penalises books with few ratings.'
            ),
            mimeType='application/json',
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """
    Returns resource data as a JSON string.
    Resources are read-only data endpoints — no arguments required.
    """
    try:
        if uri == 'books://catalogue/summary':
            data = await api_get('/api/analytics/summary/')
            return json.dumps(data, indent=2, default=str)

        elif uri == 'books://trending':
            data = await api_get(
                '/api/books/search/',
                params={'ordering': '-average_rating', 'page_size': 20}
            )
            return json.dumps(data, indent=2, default=str)

        else:
            return json.dumps({'error': f'Unknown resource: {uri}'})

    except httpx.HTTPStatusError as e:
        return json.dumps({
            'error': True,
            'status_code': e.response.status_code,
            'detail': e.response.text,
        })
    except httpx.RequestError as e:
        return json.dumps({
            'error': True,
            'detail': f'Could not connect to BookIQ at {BASE_URL}. ({str(e)})',
        })


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == '__main__':
    asyncio.run(main())

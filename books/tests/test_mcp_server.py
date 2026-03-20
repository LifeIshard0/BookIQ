"""
Smoke test for the BookIQ API endpoints used by the MCP server.

Run it from the project root with:
  python books/tests/test_mcp_server.py

Or paste it into `python manage.py shell`.

Note: full-text search results require the PostgreSQL search index to be built.
If search returns 0 rows, run:
  python manage.py build_search_index
"""

import asyncio
import os

import django
from django.apps import apps
import httpx


if not os.environ.get("DJANGO_SETTINGS_MODULE"):
	os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bookiq.settings")

if not apps.ready:
	django.setup()


BASE_URL = os.environ.get("BOOKIQ_BASE_URL", "http://127.0.0.1:8000")


async def run_mcp_tools() -> None:
	async with httpx.AsyncClient(timeout=10.0) as client:
		r = await client.get(
			f"{BASE_URL}/api/books/search/",
			params={"q": "fiction", "page_size": 3},
		)
		data = r.json()
		results = data.get("results", [])
		print(
			f"search_books: {data.get('count', 0)} results, "
			f"first: {results[0]['title'] if results else '[no results]'}"
		)

		if results:
			book_id = results[0]["id"]
			r = await client.get(f"{BASE_URL}/api/books/{book_id}/")
			book = r.json()
			print(f"get_book: {book['title']} — quality: {book['quality_score']}")
		else:
			print("get_book: skipped because search_books returned no results")

		r = await client.get(
			f"{BASE_URL}/api/books/hybrid-search/",
			params={"q": "war", "page_size": 3},
		)
		hybrid = r.json()
		hybrid_results = hybrid.get("results", [])
		first_rrf_score = (
			hybrid_results[0].get("rrf_score") if hybrid_results else None
		)
		print(
			f"hybrid_search: search_type={hybrid.get('search_type')}, "
			f"first rrf_score={first_rrf_score}"
		)


if __name__ == "__main__":
	asyncio.run(run_mcp_tools())

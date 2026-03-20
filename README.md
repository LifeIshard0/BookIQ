# COMP3011-Web-Services-and-Web-Data-CW1

Dataset: 7k Books with Metadata (Kaggle / [dylanjcastillo](https://www.kaggle.com/datasets/dylanjcastillo/7k-books-with-metadata?resource=download)) (Admin Role Required)
```
python manage.py import_books <path> --username=<username>
```

## MCP Server (AI Agent Integration)

BookIQ exposes an MCP (Model Context Protocol) server for AI agent integration.

### Tools available
| Tool | Description |
|---|---|
| `search_books` | Full-text search with filters |
| `hybrid_search_books` | RRF hybrid search (FTS + Wilson Score) |
| `get_book` | Retrieve book by UUID |
| `get_recommendations` | Personalised recommendations |
| `get_genre_trends` | Genre rating trends (admin) |
| `rate_book` | Rate a book (upsert) |

### Resources available
| Resource URI | Description |
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

Start Django, then restart Claude Desktop. BookIQ tools appear automatically.
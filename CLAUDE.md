# EventKit MCP Server

## Project Overview

MCP server for Apple Reminders via the native EventKit framework (PyObjC).
Provides CRUD tools for reminders and reminder lists.

## Architecture

- **Single-file server**: `server.py`
- **Framework**: FastMCP (MCP Python SDK)
- **Access**: PyObjC → EventKit (no auth tokens — macOS privacy prompt on first run)
- **No `.env` needed** — local system access only

## Running

```bash
uv run --with mcp --with pyobjc-framework-EventKit python server.py
```

On first run, macOS will prompt for Reminders access.
If denied, grant it in **System Settings → Privacy & Security → Reminders**.

## Available Tools

| Tool | Purpose | Destructive |
|------|---------|-------------|
| `reminders_list_lists` | List all reminder lists | No |
| `reminders_list` | List reminders (filter by list, completion) | No |
| `reminders_create` | Create a new reminder | No |
| `reminders_update` | Update title, notes, due date, completion | No |
| `reminders_delete` | Permanently delete a reminder | Yes |

## Claude Desktop / Claude Code Config

```json
{
  "mcpServers": {
    "reminders": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "run",
        "--with", "mcp",
        "--with", "pyobjc-framework-EventKit",
        "python",
        "/path/to/server.py"
      ]
    }
  }
}
```

## Known Issues / TODOs

- `NSCalendarUnit*` constants may need explicit import from `Foundation` depending on PyObjC version
- Due date round-trip uses `NSDateComponents` — verify timezone behavior matches expectations
- `store.saveReminder_commit_error_` error parameter: pass `objc.NULL` instead of `None` if save silently fails
- No support yet for: subtasks, tags, location reminders, recurring reminders

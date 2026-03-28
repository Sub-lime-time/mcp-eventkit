# mcp-eventkit

MCP server for Apple Reminders using the native [EventKit](https://developer.apple.com/documentation/eventkit) framework via PyObjC. No tokens, no sync services — reads and writes directly to the Reminders database on macOS.

> **Personal project.** PRs are not reviewed or accepted.

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)
- Reminders access granted in **System Settings → Privacy & Security → Reminders**

---

## Running

```bash
uv run --with mcp --with pyobjc-framework-EventKit python server.py
```

On first run, macOS will prompt for Reminders access. If denied, grant it in System Settings → Privacy & Security → Reminders, then restart.

---

## Available Tools

| Tool | Description | Destructive |
| ---- | ----------- | ----------- |
| `reminders_list_lists` | List all reminder lists | No |
| `reminders_list` | List reminders, filtered by list and/or completion status | No |
| `reminders_create` | Create a new reminder | No |
| `reminders_update` | Update title, notes, due date, priority, or completion | No |
| `reminders_delete` | Permanently delete a reminder | **Yes** |

All read tools support `response_format: "markdown"` (default) or `"json"`.

---

## Claude Desktop / Claude Code Config

Add to your MCP server config:

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

Replace `/path/to/server.py` with the absolute path to this file.

---

## Known Limitations

- No support for subtasks, tags, location reminders, or recurring reminders
- Due dates are stored as `NSDateComponents` — timezone behavior depends on the system calendar
- macOS only (EventKit is not available on Linux/Windows)

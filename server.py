#!/usr/bin/env python3
"""
EventKit MCP Server - Apple Reminders via EventKit.

Provides tools for reading and managing Apple Reminders using
the native EventKit framework via PyObjC.

Run with:
    uv run --with mcp --with pyobjc-framework-EventKit python server.py
"""

import asyncio
import json
import threading
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum

import objc
import EventKit
from Foundation import NSDate, NSPredicate
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# Initialize the MCP server
mcp = FastMCP("eventkit_mcp")

# Global EventKit store (one per process)
_store: Optional[Any] = None
_store_lock = threading.Lock()


# ============================================================================
# EventKit Access
# ============================================================================

def get_store() -> Any:
    """Get or create the shared EKEventStore, requesting access if needed."""
    global _store
    with _store_lock:
        if _store is not None:
            return _store

        store = EventKit.EKEventStore.alloc().init()

        # Request reminders access synchronously using a threading.Event
        granted_holder = [False]
        done = threading.Event()

        def handler(granted, error):
            granted_holder[0] = granted
            done.set()

        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeReminder,
            handler,
        )
        done.wait(timeout=10)

        if not granted_holder[0]:
            raise PermissionError(
                "Access to Reminders was denied. "
                "Grant access in System Settings → Privacy & Security → Reminders."
            )

        _store = store
        return _store


def nsdate_to_str(nsdate) -> Optional[str]:
    """Convert NSDate to ISO 8601 string, or None."""
    if nsdate is None:
        return None
    # NSDate.timeIntervalSince1970 gives Unix timestamp
    ts = nsdate.timeIntervalSince1970()
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def str_to_nsdate(iso: str) -> Any:
    """Convert ISO 8601 string to NSDate."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def reminder_to_dict(reminder) -> Dict[str, Any]:
    """Serialize an EKReminder to a plain dict."""
    due = None
    if reminder.dueDateComponents():
        # EKReminder stores due date as NSDateComponents
        cal = reminder.dueDateComponents().date()
        if cal:
            due = nsdate_to_str(cal)

    return {
        "id": str(reminder.calendarItemIdentifier()),
        "title": str(reminder.title() or ""),
        "notes": str(reminder.notes() or "") or None,
        "completed": bool(reminder.isCompleted()),
        "due": due,
        "priority": int(reminder.priority()),
        "list": str(reminder.calendar().title()),
        "list_id": str(reminder.calendar().calendarIdentifier()),
    }


def format_error(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return f"Error: {e}"
    return f"Error: {type(e).__name__}: {e}"


# ============================================================================
# Pydantic Models
# ============================================================================

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class ListRemindersInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    list_name: Optional[str] = Field(
        default=None,
        description="Filter to a specific reminder list by name. If omitted, returns all lists."
    )
    include_completed: bool = Field(
        default=False,
        description="Include completed reminders (default: incomplete only)"
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class CreateReminderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(description="Title of the reminder")
    list_name: Optional[str] = Field(
        default=None,
        description="Reminder list to add to. Defaults to the default Reminders list."
    )
    notes: Optional[str] = Field(default=None, description="Body/notes for the reminder")
    due: Optional[str] = Field(
        default=None,
        description="Due date in ISO 8601 format (e.g. '2026-04-01T09:00:00Z')"
    )
    priority: int = Field(
        default=0,
        description="Priority: 0=none, 1=high, 5=medium, 9=low",
        ge=0, le=9
    )


class UpdateReminderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reminder_id: str = Field(description="The calendarItemIdentifier of the reminder to update")
    title: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)
    completed: Optional[bool] = Field(default=None, description="Mark complete or incomplete")
    due: Optional[str] = Field(default=None, description="New due date (ISO 8601), or '' to clear")
    priority: Optional[int] = Field(default=None, ge=0, le=9)


class DeleteReminderInput(BaseModel):
    reminder_id: str = Field(description="The calendarItemIdentifier of the reminder to delete")


class ListReminderListsInput(BaseModel):
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


# ============================================================================
# MCP Tools
# ============================================================================

@mcp.tool(
    name="reminders_list_lists",
    annotations={"title": "List Reminder Lists", "readOnlyHint": True, "destructiveHint": False}
)
async def list_reminder_lists(params: ListReminderListsInput) -> str:
    """List all Reminders lists (calendars of type Reminder)."""
    try:
        store = get_store()
        calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)

        lists = [
            {
                "id": str(c.calendarIdentifier()),
                "title": str(c.title()),
                "color": str(c.color()) if c.color() else None,
            }
            for c in calendars
        ]

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(lists, indent=2)

        lines = ["# Reminder Lists\n"]
        for lst in sorted(lists, key=lambda x: x["title"]):
            lines.append(f"- **{lst['title']}** (`{lst['id']}`)")
        return "\n".join(lines)

    except Exception as e:
        return format_error(e)


@mcp.tool(
    name="reminders_list",
    annotations={"title": "List Reminders", "readOnlyHint": True, "destructiveHint": False}
)
async def list_reminders(params: ListRemindersInput) -> str:
    """List reminders, optionally filtered by list name and completion status."""
    try:
        store = get_store()
        all_calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)

        # Filter calendars if list_name specified
        if params.list_name:
            calendars = [
                c for c in all_calendars
                if str(c.title()).lower() == params.list_name.lower()
            ]
            if not calendars:
                return f"Error: No reminder list named '{params.list_name}'"
        else:
            calendars = list(all_calendars)

        # Fetch reminders synchronously
        predicate = store.predicateForRemindersInCalendars_(calendars)
        results_holder = [None]
        done = threading.Event()

        def handler(reminders):
            results_holder[0] = reminders
            done.set()

        store.fetchRemindersMatchingPredicate_completion_(predicate, handler)
        done.wait(timeout=10)

        reminders = results_holder[0] or []

        # Filter completion status
        if not params.include_completed:
            reminders = [r for r in reminders if not r.isCompleted()]

        # Sort: incomplete first, then by due date
        def sort_key(r):
            due = r.dueDateComponents()
            return (r.isCompleted(), str(due) if due else "zzz")

        reminders = sorted(reminders, key=sort_key)
        data = [reminder_to_dict(r) for r in reminders]

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        lines = [f"# Reminders ({len(data)} items)\n"]
        current_list = None
        for item in data:
            if item["list"] != current_list:
                current_list = item["list"]
                lines.append(f"\n## {current_list}\n")
            status = "~~" if item["completed"] else ""
            due = f" — due {item['due'][:10]}" if item["due"] else ""
            lines.append(f"- {status}{item['title']}{status}{due}")
            lines.append(f"  `{item['id']}`")
        return "\n".join(lines)

    except Exception as e:
        return format_error(e)


@mcp.tool(
    name="reminders_create",
    annotations={"title": "Create Reminder", "readOnlyHint": False, "destructiveHint": False}
)
async def create_reminder(params: CreateReminderInput) -> str:
    """Create a new reminder in Apple Reminders."""
    try:
        store = get_store()

        # Find target calendar
        all_calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
        if params.list_name:
            calendar = next(
                (c for c in all_calendars if str(c.title()).lower() == params.list_name.lower()),
                None
            )
            if not calendar:
                return f"Error: No reminder list named '{params.list_name}'"
        else:
            calendar = store.defaultCalendarForNewReminders()

        reminder = EventKit.EKReminder.reminderWithEventStore_(store)
        reminder.setTitle_(params.title)
        reminder.setCalendar_(calendar)

        if params.notes:
            reminder.setNotes_(params.notes)

        if params.due:
            # EKReminder due date uses NSDateComponents
            nsdate = str_to_nsdate(params.due)
            components = EventKit.NSCalendar.currentCalendar().components_fromDate_(
                EventKit.NSCalendarUnitYear | EventKit.NSCalendarUnitMonth |
                EventKit.NSCalendarUnitDay | EventKit.NSCalendarUnitHour |
                EventKit.NSCalendarUnitMinute,
                nsdate
            )
            reminder.setDueDateComponents_(components)

        if params.priority:
            reminder.setPriority_(params.priority)

        success = store.saveReminder_commit_error_(reminder, True, None)

        if not success:
            return "Error: Failed to save reminder"

        return f"Created reminder '{params.title}' in '{calendar.title()}'\nID: `{reminder.calendarItemIdentifier()}`"

    except Exception as e:
        return format_error(e)


@mcp.tool(
    name="reminders_update",
    annotations={"title": "Update Reminder", "readOnlyHint": False, "destructiveHint": False}
)
async def update_reminder(params: UpdateReminderInput) -> str:
    """Update an existing reminder (title, notes, due date, completion status, priority)."""
    try:
        store = get_store()

        reminder = store.calendarItemWithIdentifier_(params.reminder_id)
        if reminder is None:
            return f"Error: No reminder found with ID '{params.reminder_id}'"

        if params.title is not None:
            reminder.setTitle_(params.title)

        if params.notes is not None:
            reminder.setNotes_(params.notes or None)

        if params.completed is not None:
            reminder.setCompleted_(params.completed)
            if params.completed:
                reminder.setCompletionDate_(NSDate.date())

        if params.due is not None:
            if params.due == "":
                reminder.setDueDateComponents_(None)
            else:
                nsdate = str_to_nsdate(params.due)
                components = EventKit.NSCalendar.currentCalendar().components_fromDate_(
                    EventKit.NSCalendarUnitYear | EventKit.NSCalendarUnitMonth |
                    EventKit.NSCalendarUnitDay | EventKit.NSCalendarUnitHour |
                    EventKit.NSCalendarUnitMinute,
                    nsdate
                )
                reminder.setDueDateComponents_(components)

        if params.priority is not None:
            reminder.setPriority_(params.priority)

        success = store.saveReminder_commit_error_(reminder, True, None)
        if not success:
            return "Error: Failed to save changes"

        return f"Updated reminder '{reminder.title()}'"

    except Exception as e:
        return format_error(e)


@mcp.tool(
    name="reminders_delete",
    annotations={"title": "Delete Reminder", "readOnlyHint": False, "destructiveHint": True}
)
async def delete_reminder(params: DeleteReminderInput) -> str:
    """Permanently delete a reminder."""
    try:
        store = get_store()

        reminder = store.calendarItemWithIdentifier_(params.reminder_id)
        if reminder is None:
            return f"Error: No reminder found with ID '{params.reminder_id}'"

        title = str(reminder.title())
        success = store.removeReminder_commit_error_(reminder, True, None)
        if not success:
            return "Error: Failed to delete reminder"

        return f"Deleted reminder '{title}'"

    except Exception as e:
        return format_error(e)


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    mcp.run()

"""Read and write contacts.json — the contact book for email recipients."""

import json
import re
from pathlib import Path
from typing import Any

CONTACTS_PATH = Path(__file__).parent.parent / "contacts.json"

_DEFAULT_CONTACTS: dict[str, Any] = {
    "contacts": []
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load() -> dict[str, Any]:
    """Load contacts.json, creating it with defaults if it does not exist."""
    if not CONTACTS_PATH.exists():
        save(_DEFAULT_CONTACTS)
        return _DEFAULT_CONTACTS.copy()
    try:
        with CONTACTS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to read {CONTACTS_PATH}: {e}") from e


def save(data: dict[str, Any]) -> None:
    """Write the given contacts dict to contacts.json."""
    try:
        CONTACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONTACTS_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        raise RuntimeError(f"Failed to write {CONTACTS_PATH}: {e}") from e


def get_all() -> list[dict[str, Any]]:
    """Return all contacts as a list."""
    return load().get("contacts", [])


def get_by_id(contact_id: str) -> dict[str, Any] | None:
    """Return a single contact by ID, or None if not found."""
    return next((c for c in get_all() if c["id"] == contact_id), None)


def resolve_ids(contact_ids: list[str]) -> list[dict[str, Any]]:
    """Return full contact objects for the given list of IDs."""
    all_contacts = get_all()
    return [c for c in all_contacts if c["id"] in contact_ids]


def add_contact(contact_id: str, name: str, email: str, department: str) -> None:
    """Add a new contact; raises ValueError on duplicate ID or invalid email."""
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email address: {email!r}")
    data = load()
    contacts = data.get("contacts", [])
    if any(c["id"] == contact_id for c in contacts):
        raise ValueError(f"Contact with id {contact_id!r} already exists.")
    contacts.append({
        "id": contact_id,
        "name": name,
        "email": email,
        "department": department
    })
    data["contacts"] = contacts
    save(data)


def delete_contact(contact_id: str) -> None:
    """Remove the contact with the given ID from contacts.json."""
    data = load()
    data["contacts"] = [c for c in data.get("contacts", []) if c["id"] != contact_id]
    save(data)

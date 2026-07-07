"""Contacts page — manage the email recipient contact book."""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from app import contact_manager
from app.auth_manager import require_auth
from app.ui_helpers import show_logo

show_logo()
require_auth(page_title="Contacts", page_icon="👥")
st.title("👥 Contacts")

# ---------------------------------------------------------------------------
# Add Contact form
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Add Contact")

    col_name, col_email, col_dept = st.columns(3)
    with col_name:
        new_name = st.text_input("Full Name")
    with col_email:
        new_email = st.text_input("Email")
    with col_dept:
        new_dept = st.text_input("Department")

    if st.button("➕ Add Contact", type="primary"):
        if not new_name.strip() or not new_email.strip():
            st.error("Name and email are required.")
        else:
            try:
                contact_manager.add_contact(
                    contact_id=f"c{uuid.uuid4().hex[:8]}",
                    name=new_name.strip(),
                    email=new_email.strip(),
                    department=new_dept.strip(),
                )
                st.success("Contact added.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.caption("Saved in contacts.json on this PC — add once, reuse across all jobs.")

st.divider()

# ---------------------------------------------------------------------------
# Contacts table — zebra-striped via st.dataframe
# ---------------------------------------------------------------------------

st.subheader("All Contacts")

contacts = contact_manager.get_all()

if not contacts:
    st.info("No contacts yet. Add one above.")
else:
    # Build dataframe for display (no ID column shown to user)
    _rows = [
        {
            "Name": c["name"],
            "Email": c["email"],
            "Department": c.get("department", ""),
        }
        for c in contacts
    ]
    df = pd.DataFrame(_rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Email": st.column_config.TextColumn("Email", width="large"),
            "Department": st.column_config.TextColumn("Department", width="medium"),
        },
    )

    st.markdown("")
    st.markdown("**Delete a contact:**")

    # Delete buttons in a compact grid below the table
    _cols_per_row = 3
    for i in range(0, len(contacts), _cols_per_row):
        row_contacts = contacts[i : i + _cols_per_row]
        cols = st.columns(_cols_per_row)
        for col, contact in zip(cols, row_contacts):
            with col:
                label = f"🗑️ {contact['name']}"
                if st.button(label, key=f"del_{contact['id']}", use_container_width=True):
                    contact_manager.delete_contact(contact["id"])
                    st.rerun()

    st.caption(f"{len(contacts)} contact{'s' if len(contacts) != 1 else ''}")

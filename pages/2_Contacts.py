"""Contacts page — manage the email recipient contact book."""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import contact_manager

st.set_page_config(page_title="Contacts", page_icon="👥", layout="wide")
st.title("Contacts")

# ---------------------------------------------------------------------------
# Add Contact form
# ---------------------------------------------------------------------------

st.subheader("Add Contact")

col_name, col_email, col_dept = st.columns(3)
with col_name:
    new_name = st.text_input("Full Name")
with col_email:
    new_email = st.text_input("Email")
with col_dept:
    new_dept = st.text_input("Department")

if st.button("Add Contact"):
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
# Contacts table
# ---------------------------------------------------------------------------

st.subheader("All Contacts")

contacts = contact_manager.get_all()

if not contacts:
    st.info("No contacts yet. Add one above.")
else:
    h_name, h_email, h_dept, h_del = st.columns([3, 4, 3, 1])
    h_name.markdown("**Name**")
    h_email.markdown("**Email**")
    h_dept.markdown("**Department**")
    h_del.markdown("**Delete**")

    for contact in contacts:
        c_name, c_email, c_dept, c_del = st.columns([3, 4, 3, 1])
        c_name.write(contact["name"])
        c_email.write(contact["email"])
        c_dept.write(contact.get("department", ""))
        if c_del.button("✕", key=f"del_{contact['id']}"):
            contact_manager.delete_contact(contact["id"])
            st.rerun()

    st.caption(f"{len(contacts)} contact{'s' if len(contacts) != 1 else ''}")

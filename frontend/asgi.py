"""ASGI entry point for the private Streamlit service."""

from pathlib import Path

import streamlit as st

# Uvicorn owns the Unix socket. The public Streamlit App API handles ASGI.
app = st.App(Path(__file__).with_name("app.py"))

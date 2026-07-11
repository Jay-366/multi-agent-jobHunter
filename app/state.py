"""st.session_state helpers — the UI's per-session memory (candidate, target, last run)."""
from __future__ import annotations

import streamlit as st


def init_state() -> None:
    st.session_state.setdefault("candidate", None)
    st.session_state.setdefault("target", None)
    st.session_state.setdefault("last_run", None)


def set_profile(candidate, target) -> None:
    st.session_state["candidate"] = candidate
    st.session_state["target"] = target


def set_last_run(state) -> None:
    st.session_state["last_run"] = state

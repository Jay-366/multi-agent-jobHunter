"""Tracker — the jobs from your latest hunt, with salary, a link, and an editable status.

Scoped to the last run (not every run ever): the table shows exactly what you just hunted.
Status is a dropdown you can change and save; it persists in data/statuses.json. No AI calls.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app import backend, state

st.set_page_config(page_title="Tracker · jobHunter", page_icon="🗂️", layout="wide")
state.init_state()

st.title("🗂️ Tracker")
st.caption("Jobs from your latest hunt. Set each job's **Status** and click Save — it sticks.")

run = st.session_state.get("last_run") or backend.load_last_run()
if run is None:
    st.info("No run yet — go to **Hunt** in the sidebar. The jobs you hunt show up here.")
    st.stop()

rows = backend.tracker_view(run)
if not rows:
    st.info("The last run evaluated no jobs. Try a **Hunt** with a higher limit.")
    st.stop()

edited = st.data_editor(
    rows,
    use_container_width=True,
    hide_index=True,
    disabled=["Rank", "Company", "Role", "Salary", "Score", "Verdict", "Link", "posting_id"],
    column_order=["Rank", "Company", "Role", "Salary", "Score", "Verdict", "Status", "Link"],
    column_config={
        "Score": st.column_config.NumberColumn("Score", format="%.1f", help="Overall 0–10"),
        "Salary": st.column_config.TextColumn("Salary"),
        "Link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
        "Status": st.column_config.SelectboxColumn(
            "Status", options=backend.STATUS_OPTIONS, required=True,
            help="Where this application stands — change it and click Save."),
        "posting_id": None,  # keep for save mapping, but hidden
    },
    key="tracker_editor",
)

c1, c2, _ = st.columns([1, 1, 4])
if c1.button("💾 Save statuses", type="primary"):
    mapping = backend.load_statuses()
    for r in edited:
        mapping[r["posting_id"]] = r["Status"]
    backend.save_statuses(mapping)
    st.success("Statuses saved to data/statuses.json.")

st.divider()
e1, e2 = st.columns(2)
if e1.button("Export CSV"):
    from src.services.export import export_csv
    st.success(f"Wrote {export_csv(backend.DATA_DIR)}")
if e2.button("Export JSON"):
    from src.services.export import export_json
    st.success(f"Wrote {export_json(backend.DATA_DIR)}")

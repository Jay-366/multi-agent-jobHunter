"""jobHunter — Streamlit Home. Overview + live status. Transport only.

Launch:  streamlit run app/Home.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root importable

import streamlit as st

from app import backend, state

st.set_page_config(page_title="jobHunter", page_icon="🎯", layout="wide")
state.init_state()

st.title("🎯 multi-agent jobHunter")
st.caption("Discover → score → track → tailor → coach — Malaysia. A human reviews and applies; "
           "this tool never applies for you.")

snap = backend.status_snapshot()
c1, c2, c3 = st.columns(3)
c1.metric("DeepSeek API key", "✅ set" if snap["key_present"] else "❌ missing")
c2.metric("Profile", "✅ ready" if snap["profile_exists"] else "— none yet")
c3.metric("Tracker rows", snap["tracker_rows"])

if not snap["key_present"]:
    st.warning("No `DEEPSEEK_API_KEY` found. Copy `.env.example` to `.env` and add your key, "
               "then reload.")

st.divider()
st.subheader("How it works")
st.markdown(
    "1. **Onboard** — turn a resume + a plain-English wish into a saved profile.\n"
    "2. **Hunt** — discover live Malaysian jobs, score each against you, and track them.\n"
    "3. **Results** — read per-job scores + evidence, a tailored CV, and an interview prep pack.\n"
    "4. **Tracker** — your full application history.\n"
    "5. **Tune** — drag scoring weights to re-rank instantly (no AI cost)."
)

st.info("Use the sidebar to move between pages. Start with **Onboard** if you have no profile yet.")

"""Tune — drag scoring weights to re-rank the last run INSTANTLY (no AI cost) + settings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app import backend, state

st.set_page_config(page_title="Tune · jobHunter", page_icon="🎚️", layout="wide")
state.init_state()

st.title("🎚️ Tune")
st.caption("Re-rank by your priorities. Weights re-rank instantly with **no AI call** — "
           "they reuse the raw scores from your last run.")

run = st.session_state.get("last_run") or backend.load_last_run()

DIMS = ["role_match", "skills", "comp", "location", "growth", "legitimacy"]
defaults = backend.default_weights()

st.subheader("Scoring weights")
cols = st.columns(3)
weights = {}
for i, d in enumerate(DIMS):
    weights[d] = cols[i % 3].slider(d, 0.0, 1.0,
                                    float(defaults.get(d, 1.0 / len(DIMS))), 0.05)
threshold = st.slider("Apply threshold (verdict = Apply if overall ≥ this)", 0.0, 10.0,
                      backend.default_threshold(), 0.5)

st.subheader("Re-ranked shortlist")
if run and run.evaluations:
    postings = {p.id: p for p in run.postings}
    for e in backend.rerank(run, weights=weights, threshold=threshold):
        p = postings.get(e.posting_id)
        title = p.title if p else e.posting_id
        company = p.company if p else "?"
        st.markdown(f"- **#{e.rank}** · {e.overall}/10 · **{e.verdict}** — {title} @ {company}")
else:
    st.info("No run to re-rank yet — run a **Hunt** first. You can still save weights below.")

if st.button("💾 Save weights to config", type="primary"):
    backend.save_weights(weights, threshold)
    st.success("Saved. The CLI and future hunts will use these weights.")

st.divider()
st.subheader("Run settings (take effect on the next Hunt)")
snap = backend.run_settings_snapshot()
st.json(snap)
new_steps = st.number_input("analyst max_steps", min_value=1, max_value=10,
                            value=snap["max_steps"])
if st.button("Save run settings"):
    backend.save_config({"analyst": {"max_steps": int(new_steps)}})
    st.success("Saved run settings.")

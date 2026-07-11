"""Results — explore a completed run: scores, evidence, JD, tailored CV, prep pack.

Reads only from session_state / persisted run / disk. Makes ZERO LLM/network calls.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app import backend, state

st.set_page_config(page_title="Results · jobHunter", page_icon="📊", layout="wide")
state.init_state()

st.title("📊 Results")

run = st.session_state.get("last_run") or backend.load_last_run()
if run is None:
    st.info("No run yet. Go to **Hunt** in the sidebar to run a search — results will appear here.")
    st.stop()

st.caption(f"{len(run.evaluations)} evaluated · needs human review: **{run.needs_human_review}** "
           "· this page makes no AI calls.")

postings = {p.id: p for p in run.postings}

for ev in run.evaluations:
    p = postings.get(ev.posting_id)
    title = p.title if p else ev.posting_id
    company = p.company if p else "?"
    with st.expander(f"#{ev.rank} · {ev.overall}/10 · {ev.verdict} — {title} @ {company}"):
        t_scores, t_jd, t_cv, t_prep = st.tabs(["Scores", "JD", "Tailored CV", "Prep pack"])

        with t_scores:
            st.write(f"**Overall:** {ev.overall}/10 · **Verdict:** {ev.verdict} · "
                     f"**Legitimacy:** {ev.legitimacy}/10")
            for d in ev.dimensions:
                st.markdown(f"- **{d.name}** — {d.raw}/10 · {d.evidence}")

        with t_jd:
            if p:
                st.write(f"**Salary:** {p.salary_text or 'n/a'}  ·  **URL:** {p.url}")
            st.markdown(p.description if (p and p.description) else "_(no JD fetched)_")

        with t_cv:
            cv = backend.read_material(ev.posting_id, "cv")
            if cv:
                cand_name = run.candidate.name if run.candidate else None
                d1, d2 = st.columns(2)
                d1.download_button("Download CV (.md)", cv, file_name=f"{ev.posting_id}-cv.md",
                                   key=f"cv-md-{ev.posting_id}")
                try:
                    pdf = backend.render_cv_pdf(ev.posting_id, name=cand_name)
                    if pdf:
                        d2.download_button("Download CV (.pdf)", pdf, mime="application/pdf",
                                           file_name=f"{ev.posting_id}-cv.pdf",
                                           key=f"cv-pdf-{ev.posting_id}", type="primary")
                except Exception as e:  # PDF is a bonus view — never break the page over it
                    d2.caption(f"PDF unavailable: {e}")
                st.markdown(cv)
            else:
                st.caption("No tailored CV. Re-run **Hunt** with “Tailor a CV” checked.")

        with t_prep:
            prep = backend.read_material(ev.posting_id, "prep")
            if prep:
                st.download_button("Download prep (.md)", prep, file_name=f"{ev.posting_id}-prep.md",
                                   key=f"prep-{ev.posting_id}")
                st.markdown(prep)
            else:
                st.caption("No prep pack. Re-run **Hunt** with “Build a prep pack” checked.")

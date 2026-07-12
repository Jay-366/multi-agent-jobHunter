"""Onboard — resume + wish → saved profile. Transport only (calls app.backend)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app import backend, state

st.set_page_config(page_title="Onboard · jobHunter", page_icon="📝")
state.init_state()

st.title("📝 Onboard")
st.caption("Turn a resume + a plain-English wish into a saved profile (data/profile.yml).")

if not backend.key_present():
    st.error("No `DEEPSEEK_API_KEY` set — add it to `.env` and reload before onboarding.")

uploaded = st.file_uploader("Resume (.txt, .md, or .pdf)", type=["txt", "md", "pdf"])
pasted = st.text_area("…or paste your resume text", height=200)
wish = st.text_input("Your job wish",
                     placeholder="senior ML engineer in Kuala Lumpur, remote ok, ~RM12000")

resume_text = ""
if uploaded is not None:
    try:
        resume_text, quality = backend.extract_resume(uploaded.name, uploaded.getvalue())
    except Exception as e:
        st.error(f"Could not read {uploaded.name}: {e}")
    else:
        st.caption(f"Extracted **{quality['chars']} chars / {quality['words']} words** "
                   f"from {uploaded.name}.")
        if not quality["ok"]:
            for reason in quality["reasons"]:
                st.warning(reason)
            with st.expander("Preview extracted text"):
                st.text(resume_text[:2000])
elif pasted.strip():    
    resume_text = pasted

st.caption("Creating a profile makes **1 AI call** (the `pro` model).")
if st.button("Create profile", type="primary"):
    if not resume_text.strip():
        st.warning("Provide a resume — upload a `.txt`/`.md`/`.pdf` file or paste text above.")
    elif not wish.strip():
        st.warning("Enter your job wish.")
    else:
        with st.spinner("Extracting profile…"):
            try:
                result = backend.onboard(resume_text, wish)
            except Exception as e:  # missing key, bad LLM output, etc. — show, don't crash
                st.error(f"Onboarding failed: {e}")
                result = None
        if result is not None:
            state.set_profile(result.candidate, result.target)
            st.success("Profile saved to data/profile.yml")
            c, t = result.candidate, result.target
            st.subheader("Candidate")
            st.write(f"**{c.name}** — {len(c.skills)} skills")
            if c.skills:
                st.write("Skills: " + ", ".join(c.skills))
            st.subheader("Target")
            st.write(f"**Keywords:** {', '.join(t.keywords)}")
            st.write(f"**Location:** {t.location} ({t.country})  ·  "
                     f"**Salary min:** {t.salary_min}  ·  **Remote ok:** {t.remote_ok}")
            st.info("Next: go to **Hunt** in the sidebar to run the search.")

"""Hunt — configure + run the pipeline with live progress → shortlist. Transport only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app import backend, state

st.set_page_config(page_title="Hunt · jobHunter", page_icon="🔍")
state.init_state()

st.title("🔍 Hunt")
st.caption("Discover live Malaysian jobs, score each against your profile, and track them.")

if not backend.profile_exists():
    st.warning("No profile yet — go to **Onboard** in the sidebar first.")
    st.stop()

from src.config import settings  # read-only display of current knobs

disc = settings.discovery
max_steps = int(settings.analyst.get("max_steps", 3))
st.caption(f"Providers: **{', '.join(disc.get('providers', []))}** · "
           f"analyst model: **{settings.model_name('pro')}** · max_steps: **{max_steps}**")

limit = st.number_input("Jobs to evaluate", min_value=1, max_value=20, value=3, step=1)
c1, c2 = st.columns(2)
do_tailor = c1.checkbox("Also tailor a CV per Apply job")
do_coach = c2.checkbox("Also build a prep pack per Apply job")

extra = " + tailoring/coaching for each Apply job" if (do_tailor or do_coach) else ""
st.info(f"This makes roughly **{limit}–{limit * max_steps} AI calls**{extra}. Expect a few minutes.")


def _render_shortlist(run) -> None:
    if not run.evaluations:
        st.warning("No evaluations produced (no live postings matched, or all were filtered).")
        return
    st.subheader(f"Ranked shortlist — needs review: {run.needs_human_review}")
    postings = {p.id: p for p in run.postings}
    for ev in run.evaluations:
        p = postings.get(ev.posting_id)
        title = p.title if p else ev.posting_id
        company = p.company if p else "?"
        st.write(f"**#{ev.rank}** · {ev.overall}/10 · **{ev.verdict}** — {title} @ {company}")
    st.info("See **Results** for per-job scores, evidence, tailored CV and prep pack. "
            "This tool never applies for you.")


if st.button("Run hunt", type="primary"):
    from app.trace import event_markdown

    st.caption("🧠 = agent thinking · 🔧 = tool call · ✅ = result — watch the agents work below.")
    log: list[str] = []
    result = None
    with st.status("Hunting… the agents are working", expanded=True) as status:
        def writer(item) -> None:
            # item may be a rich AgentEvent (thought/tool/result) or a plain string.
            log.append(str(item))
            status.markdown(event_markdown(item))

        try:
            result = backend.run_hunt(limit=int(limit), tailor=do_tailor,
                                      coach=do_coach, progress=writer)
            status.update(label="Hunt complete ✅", state="complete", expanded=False)
        except Exception as e:
            status.update(label="Hunt failed", state="error")
            st.error(f"Hunt failed: {e}")

    if result is not None:
        state.set_last_run(result)
        for err in result.errors:
            st.warning(err)
        _render_shortlist(result)
        with st.expander("Raw run log"):
            st.code("\n".join(log) or "(no progress emitted)")

"""jobhunter CLI — the thin transport (ARCHITECTURE §5, §11). One file, no src/api/.

Three commands, and a hard human-review gate: the tool prepares and evaluates; a HUMAN
reviews and applies. There is deliberately NO apply/submit path anywhere in this system.

    jobhunter onboard --resume data/profile.md --wish "..."   -> writes data/profile.yml
    jobhunter run                                             -> discover→score→track→shortlist
    jobhunter status                                          -> reprint the tracker table

Commands stay thin: they parse args, call services/agents/orchestration, and print. All
real work lives below this layer. Collaborators are injectable so the CLI tests hermetically.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from src.events import AgentEvent
from src.models import Candidate, SearchTarget

_DEFAULT_PROFILE = "data/profile.yml"
_REVIEW_NOTICE = (
    "\nThis tool never applies on your behalf. Review the shortlist and the reports in "
    "data/reports/, then apply yourself to the ones worth it."
)


# --- profile persistence --------------------------------------------------- #
def save_profile(candidate: Candidate, target: SearchTarget, out_path: str | Path) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {"candidate": candidate.model_dump(), "target": target.model_dump()}
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_profile(path: str | Path) -> tuple[Candidate, SearchTarget]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No profile at {p}. Run 'jobhunter onboard' first.")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Candidate.model_validate(data["candidate"]), SearchTarget.model_validate(data["target"])


# --- commands -------------------------------------------------------------- #
def cmd_onboard(resume: str, wish: str, out: str, agent=None) -> int:
    from src.services.resume_loader import load_resume

    try:
        resume_text = load_resume(resume)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if agent is None:
        from src.agents.onboarding import OnboardingAgent
        agent = OnboardingAgent()
    try:
        result = agent.run(resume_text, wish)
    except RuntimeError as e:  # e.g. missing DEEPSEEK_API_KEY
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: onboarding failed: {e}", file=sys.stderr)
        return 1
    save_profile(result.candidate, result.target, out)
    print(f"Saved profile to {out}")
    print(f"  candidate: {result.candidate.name} — {len(result.candidate.skills)} skills")
    print(f"  target:    {', '.join(result.target.keywords)} in {result.target.location} "
          f"({result.target.country})")
    return 0


def cmd_run(profile: str, limit: int, tailor: bool = False, coach: bool = False,
            data_dir: str = "data", pipeline=None, tracker=None,
            tailor_agent=None, coach_agent=None) -> int:
    try:
        candidate, target = load_profile(profile)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    progress = lambda m: print(m, file=sys.stderr, flush=True)
    if pipeline is None:
        from src.config import settings
        from src.orchestration.graph import Pipeline
        from src.services.discovery import discover
        disc = settings.discovery
        dedup_on = bool(disc.get("dedup", True))
        pipeline = Pipeline(
            max_evaluations=limit, progress=progress,
            check_liveness=bool(disc.get("liveness", True)),
            discover_fn=lambda t: discover(t, deduplicate=dedup_on),
        )
    if tracker is None:
        from src.services.tracker import Tracker
        tracker = Tracker(data_dir)

    try:
        state = pipeline.invoke(candidate, target)
    except RuntimeError as e:  # e.g. missing DEEPSEEK_API_KEY surfaced by the analyst
        print(f"error: {e}", file=sys.stderr)
        return 1

    summary = tracker.save(state)
    _print_shortlist(state, summary)

    if tailor or coach:
        _prepare_materials(candidate, state, data_dir, tailor, coach,
                           tailor_agent, coach_agent, progress)

    for err in state.errors:
        print(f"  warning: {err}", file=sys.stderr)
    print(_REVIEW_NOTICE)
    return 0


def _prepare_materials(candidate, state, data_dir, do_tailor, do_coach,
                       tailor_agent, coach_agent, progress) -> None:
    """For each Apply-verdict job, optionally tailor a CV and/or build a prep pack."""
    from src.services.render import render_markdown

    apply_evals = [e for e in state.evaluations if e.verdict == "Apply"]
    if not apply_evals:
        progress("No 'Apply' jobs to prepare materials for.")
        return
    if do_tailor and tailor_agent is None:
        from src.agents.tailor import TailorAgent
        tailor_agent = TailorAgent()
    if do_coach and coach_agent is None:
        from src.agents.coach import CoachAgent
        coach_agent = CoachAgent()

    postings = {p.id: p for p in state.postings}
    outdir = Path(data_dir) / "outputs"
    outdir.mkdir(parents=True, exist_ok=True)

    made = 0
    for ev in apply_evals:
        posting = postings.get(ev.posting_id)
        label = posting.company if posting else ev.posting_id
        if do_tailor:
            progress(AgentEvent("tailor", "job", f"Tailoring CV — {label}"))
            try:
                draft = tailor_agent.run(candidate, ev, posting, emit=progress)
                (outdir / f"{ev.posting_id}-cv.md").write_text(
                    render_markdown(draft), encoding="utf-8")
                made += 1
            except Exception as e:  # one job's failure must not sink the others
                progress(AgentEvent("tailor", "error", f"tailor failed for {label}: {e}"))
        if do_coach:
            progress(AgentEvent("coach", "job", f"Building prep pack — {label}"))
            try:
                pack = coach_agent.run(candidate, ev, posting, emit=progress)
                (outdir / f"{ev.posting_id}-prep.md").write_text(
                    _render_prep(pack, label), encoding="utf-8")
                made += 1
            except Exception as e:
                progress(AgentEvent("coach", "error", f"coach failed for {label}: {e}"))
    print(f"\nPrepared {made} material file(s) in {outdir}/ for "
          f"{len(apply_evals)} 'Apply' job(s).")


def _render_prep(pack, label: str) -> str:
    lines = [f"# Interview prep — {label}", "", "## Skill gaps"]
    lines += [f"- {g}" for g in pack.skill_gaps] or ["- (none)"]
    lines += ["", "## Study plan"] + [f"{i}. {s}" for i, s in enumerate(pack.study_plan, 1)]
    lines += ["", "## Mock questions"] + [f"{i}. {q}" for i, q in enumerate(pack.mock_questions, 1)]
    return "\n".join(lines) + "\n"


def cmd_status(data_dir: str = "data") -> int:
    path = Path(data_dir) / "applications.md"
    if not path.exists():
        print("No applications yet. Run 'jobhunter onboard' then 'jobhunter run'.")
        return 0
    print(path.read_text(encoding="utf-8"))
    return 0


def _print_shortlist(state, summary: dict) -> None:
    reports = {e["posting_id"]: e["report"] for e in summary.get("entries", [])}
    postings = {p.id: p for p in state.postings}
    if not state.evaluations:
        print("No evaluations produced (no live postings matched, or all were filtered).")
        return
    print(f"\nRanked shortlist ({len(state.evaluations)} evaluated, "
          f"needs_human_review={state.needs_human_review}):\n")
    for ev in state.evaluations:
        p = postings.get(ev.posting_id)
        title = p.title if p else ev.posting_id
        company = p.company if p else "?"
        score = "n/a" if ev.overall is None else f"{ev.overall:g}/10"
        print(f"  #{ev.rank:<2} {score:>7}  {ev.verdict or '?':5}  {title} @ {company}")
        print(f"        report: {reports.get(ev.posting_id, '(n/a)')}")


# --- arg parsing ----------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobhunter", description="Multi-agent job hunter (MY).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_on = sub.add_parser("onboard", help="resume + wish -> saved profile")
    p_on.add_argument("--resume", required=True, help="path to a .txt/.md resume")
    p_on.add_argument("--wish", required=True, help="plain-English job wish")
    p_on.add_argument("--out", default=_DEFAULT_PROFILE, help="where to save the profile")

    p_run = sub.add_parser("run", help="discover -> score -> track -> shortlist (+ optional prep)")
    p_run.add_argument("--profile", default=_DEFAULT_PROFILE)
    p_run.add_argument("--limit", type=int, default=5, help="max jobs to evaluate")
    p_run.add_argument("--tailor", action="store_true",
                       help="also tailor a CV for each 'Apply' job (data/outputs/)")
    p_run.add_argument("--coach", action="store_true",
                       help="also build an interview prep pack for each 'Apply' job")
    p_run.add_argument("--all", action="store_true",
                       help="shorthand for --tailor --coach (the whole pipeline)")

    sub.add_parser("status", help="reprint the tracker table")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "onboard":
        return cmd_onboard(args.resume, args.wish, args.out)
    if args.command == "run":
        return cmd_run(args.profile, args.limit,
                       tailor=args.tailor or args.all, coach=args.coach or args.all)
    if args.command == "status":
        return cmd_status()
    return 1  # unreachable (subparser required)


if __name__ == "__main__":
    raise SystemExit(main())

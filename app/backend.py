"""The ONLY bridge between the Streamlit UI and the src/ backend.

Every non-trivial call a page makes goes through here; pages never import src/ logic
directly. This module reuses the existing agents/services/orchestration — it never
reimplements scoring, tracking, tailoring, etc. (STREAMLIT_PLAN.md invariants).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable whether launched via `streamlit run app/Home.py`,
# Streamlit multipage, or streamlit.testing.AppTest.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402

DATA_DIR = ROOT / "data"
PROFILE_PATH = DATA_DIR / "profile.yml"


# --- F0: status snapshot for the Home page --------------------------------- #
def key_present() -> bool:
    try:
        return bool(settings.deepseek_api_key)
    except Exception:
        return False


def profile_exists() -> bool:
    return PROFILE_PATH.exists()


def tracker_row_count() -> int:
    from src.services.tracker import Tracker
    try:
        return len(Tracker(str(DATA_DIR))._load_rows())
    except Exception:
        return 0


def status_snapshot() -> dict:
    return {
        "key_present": key_present(),
        "profile_exists": profile_exists(),
        "tracker_rows": tracker_row_count(),
    }


# --- resume extraction (txt/md/pdf) + quality gate ------------------------- #
def extract_resume(filename: str, data: bytes) -> tuple[str, dict]:
    """Extract resume text from an uploaded file and return (text, validation)."""
    from src.services.resume_loader import extract_resume_bytes, validate_resume_text

    text = extract_resume_bytes(filename, data)
    return text, validate_resume_text(text)


# --- F1: onboarding -------------------------------------------------------- #
def onboard(resume_text: str, wish: str, agent=None, out_path: Path | None = None):
    """Reuse OnboardingAgent + cli.save_profile. Returns the OnboardingOutput."""
    from src.agents.onboarding import OnboardingAgent
    from src.cli import save_profile

    agent = agent or OnboardingAgent()
    result = agent.run(resume_text, wish)
    save_profile(result.candidate, result.target, out_path or PROFILE_PATH)
    return result


# --- F1: run the hunt + persist the whole run ------------------------------ #
def _last_run_path(data_dir: Path) -> Path:
    return data_dir / "last_run.json"


def save_last_run(state, data_dir: Path | None = None) -> Path:
    dd = data_dir or DATA_DIR
    dd.mkdir(parents=True, exist_ok=True)
    path = _last_run_path(dd)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_last_run(data_dir: Path | None = None):
    """Return the persisted JobHuntState, or None if there is no saved run."""
    from src.orchestration.state import JobHuntState

    path = _last_run_path(data_dir or DATA_DIR)
    if not path.exists():
        return None
    return JobHuntState.model_validate_json(path.read_text(encoding="utf-8"))


def run_hunt(limit: int, tailor: bool = False, coach: bool = False, progress=None,
             data_dir: Path | None = None, pipeline=None,
             tailor_agent=None, coach_agent=None):
    """Full hunt: pipeline → tracker → optional tailor/coach → persist. Returns JobHuntState.

    Reuses Pipeline, Tracker, and cli._prepare_materials — no orchestration is reimplemented.
    """
    from src.cli import _prepare_materials, load_profile
    from src.services.tracker import Tracker

    dd = data_dir or DATA_DIR
    progress = progress or (lambda _m: None)
    candidate, target = load_profile(dd / "profile.yml")

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

    state = pipeline.invoke(candidate, target)
    Tracker(str(dd)).save(state)
    if tailor or coach:
        _prepare_materials(candidate, state, str(dd), tailor, coach,
                           tailor_agent, coach_agent, progress)
    save_last_run(state, dd)
    return state


# --- F1: instant re-rank (PURE math — never calls the LLM) ----------------- #
def rerank(state, weights: dict | None = None, threshold: float | None = None):
    """Re-score + re-rank a run's evaluations with new weights. No LLM, no network."""
    from src.services.scoring import rank, score_evaluation

    rescored = [score_evaluation(e, weights=weights, threshold=threshold)
                for e in state.evaluations]
    return rank(rescored)


# --- F1: read canonical artifacts for the UI ------------------------------- #
def read_tracker(data_dir: Path | None = None) -> list[dict]:
    from src.services.tracker import Tracker

    return Tracker(str(data_dir or DATA_DIR))._load_rows()


def read_report(rel_or_abs_path: str, data_dir: Path | None = None) -> str | None:
    dd = data_dir or DATA_DIR
    p = Path(rel_or_abs_path)
    if not p.is_absolute():
        p = dd / rel_or_abs_path
    return p.read_text(encoding="utf-8") if p.exists() else None


def read_material(posting_id: str, kind: str, data_dir: Path | None = None) -> str | None:
    """kind in {'cv', 'prep'} → data/outputs/<id>-cv.md | <id>-prep.md."""
    dd = data_dir or DATA_DIR
    p = dd / "outputs" / f"{posting_id}-{kind}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def posting_by_id(state, posting_id: str):
    return next((p for p in state.postings if p.id == posting_id), None)


# --- tailored CV → printable Harvard-style PDF ----------------------------- #
def render_cv_pdf(posting_id: str, name: str | None = None,
                  data_dir: Path | None = None) -> bytes | None:
    """Render a job's tailored CV (data/outputs/<id>-cv.md) to PDF bytes, or None if absent."""
    md = read_material(posting_id, "cv", data_dir)
    if not md:
        return None
    from src.services.pdf_render import render_resume_pdf

    return render_resume_pdf(md, name=name, title=f"{name or 'Tailored'} — CV")


# --- F5: run-scoped, interactive tracker ----------------------------------- #
# Statuses the user can set per job. Persisted in data/statuses.json by posting_id.
STATUS_OPTIONS = ["To review", "Interested", "Applied", "Interviewing",
                  "Offer", "Rejected", "Not a fit"]
_VERDICT_TO_STATUS = {"Apply": "Interested", "Review": "To review", "Skip": "Not a fit"}


def default_status_for(verdict: str | None) -> str:
    return _VERDICT_TO_STATUS.get(verdict or "", "To review")


def _statuses_path(data_dir: Path) -> Path:
    return data_dir / "statuses.json"


def load_statuses(data_dir: Path | None = None) -> dict:
    import json

    p = _statuses_path(data_dir or DATA_DIR)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_statuses(mapping: dict, data_dir: Path | None = None) -> Path:
    import json

    dd = data_dir or DATA_DIR
    dd.mkdir(parents=True, exist_ok=True)
    path = _statuses_path(dd)
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _salary_text(p) -> str:
    if getattr(p, "salary_text", None):
        return p.salary_text
    if getattr(p, "salary_min", None) or getattr(p, "salary_max", None):
        cur = p.salary_currency or ""
        lo = f"{p.salary_min:g}" if p.salary_min else ""
        hi = f"{p.salary_max:g}" if p.salary_max else ""
        rng = "–".join(x for x in (lo, hi) if x)
        per = f"/{p.salary_period}" if p.salary_period else ""
        return f"{cur} {rng}{per}".strip()
    return "n/a"


def tracker_view(run, data_dir: Path | None = None) -> list[dict]:
    """One row per job in THIS run: rank, company, role, salary, score, verdict, status, link.

    Status defaults from the verdict, then is overridden by any saved user choice — so the
    tracker reflects the hunt you just ran, with a status you can edit and keep.
    """
    statuses = load_statuses(data_dir)
    postings = {p.id: p for p in run.postings}
    rows: list[dict] = []
    for ev in sorted(run.evaluations, key=lambda e: (e.rank if e.rank is not None else 9999)):
        p = postings.get(ev.posting_id)
        rows.append({
            "Rank": ev.rank,
            "Company": p.company if p else "?",
            "Role": p.title if p else ev.posting_id,
            "Salary": _salary_text(p) if p else "n/a",
            "Score": ev.overall,
            "Verdict": ev.verdict,
            "Status": statuses.get(ev.posting_id) or default_status_for(ev.verdict),
            "Link": (p.url if p else "") or "",
            "posting_id": ev.posting_id,
        })
    return rows


# --- F6: scoring defaults + config writes ---------------------------------- #
def default_weights() -> dict:
    return {k: float(v) for k, v in settings.scoring.get("weights", {}).items()}


def default_threshold() -> float:
    return float(settings.scoring.get("threshold", 6.0))


def run_settings_snapshot() -> dict:
    return {
        "providers": list(settings.discovery.get("providers", [])),
        "max_steps": int(settings.analyst.get("max_steps", 3)),
        "pro_model": settings.model_name("pro"),
        "flash_model": settings.model_name("flash"),
        "dedup": bool(settings.discovery.get("dedup", True)),
        "liveness": bool(settings.discovery.get("liveness", True)),
    }


def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def save_config(updates: dict, config_path=None) -> None:
    """Deep-merge `updates` into config.yaml and refresh the cached settings."""
    import yaml

    from src.config import CONFIG_PATH, get_settings

    path = Path(config_path) if config_path else CONFIG_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _deep_merge(data, updates)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        get_settings.cache_clear()  # so a re-read reflects the change
    except Exception:
        pass


def save_weights(weights: dict, threshold: float | None = None, config_path=None) -> None:
    scoring: dict = {"weights": {k: float(v) for k, v in weights.items()}}
    if threshold is not None:
        scoring["threshold"] = float(threshold)
    save_config({"scoring": scoring}, config_path=config_path)

"""Tracker — canonical, human-readable, git-diffable files (ARCHITECTURE §8).

Writes three things under a data directory:
  - pipeline.md         : the inbox of discovered postings (pending)
  - applications.md     : the master table (source of truth), one row per evaluated job
  - reports/NNN-*.md    : the full evaluation per job (JD + per-dimension scores + evidence)

Two guarantees:
  * Atomic writes  — temp file + os.replace, so a killed write never corrupts a file.
  * Idempotent     — a job is keyed by (company, role); re-running updates its row and
                     overwrites its report rather than adding duplicates. The report's
                     NNN and date are assigned once and reused on later runs.

This is the ONLY place system code writes into data/ at runtime (Invariants).
"""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from src.models import Evaluation, JobPosting
from src.orchestration.state import JobHuntState

_WS = re.compile(r"\s+")
_SLUG = re.compile(r"[^a-z0-9]+")
_REPORT_RE = re.compile(r"\((reports/(\d+)-[^)]+\.md)\)")


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower())


def _slug(s: str) -> str:
    return _SLUG.sub("-", (s or "").lower()).strip("-") or "job"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem (incl. Windows)


class Tracker:
    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self.reports_dir = self.data_dir / "reports"

    # --- public ------------------------------------------------------------ #
    def save(self, state: JobHuntState) -> dict:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        rows = self._load_rows()
        index = {(_norm(r["company"]), _norm(r["role"])): r for r in rows}
        postings = {p.id: p for p in state.postings}
        entries: list[dict] = []

        for ev in state.evaluations:
            posting = postings.get(ev.posting_id) or JobPosting(
                id=ev.posting_id, source="jobstreet", title=ev.posting_id,
                company="(unknown)", url="",
            )
            key = (_norm(posting.company), _norm(posting.title))
            row = index.get(key)
            if row is None:
                nnn = self._next_nnn(rows)
                today = date.today().isoformat()
                report = f"{nnn:03d}-{_slug(posting.company)}-{today}.md"
                row = {"date": today, "company": posting.company, "role": posting.title,
                       "report": f"reports/{report}"}
                rows.append(row)
                index[key] = row
            # update mutable fields (idempotent overwrite of report)
            row["score"] = "" if ev.overall is None else f"{ev.overall:g}"
            row["status"] = ev.verdict or ""
            _atomic_write(self.data_dir / row["report"], _render_report(posting, ev))
            entries.append({"posting_id": posting.id, "company": posting.company,
                            "role": posting.title, "report": row["report"],
                            "score": row["score"], "status": row["status"]})

        _atomic_write(self.data_dir / "applications.md", _render_table(rows))
        _atomic_write(self.data_dir / "pipeline.md", _render_pipeline(state.postings))
        return {"rows": len(rows),
                "reports": len(list(self.reports_dir.glob("*.md"))),
                "entries": entries}

    # --- internals --------------------------------------------------------- #
    def _load_rows(self) -> list[dict]:
        path = self.data_dir / "applications.md"
        if not path.exists():
            return []
        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 6 or cells[0] in ("Date", "----") or set(cells[0]) <= {"-", ":"}:
                continue
            m = _REPORT_RE.search(cells[5])
            report = m.group(1) if m else ""
            rows.append({"date": cells[0], "company": cells[1], "role": cells[2],
                         "score": cells[3], "status": cells[4], "report": report})
        return rows

    @staticmethod
    def _next_nnn(rows: list[dict]) -> int:
        nums = []
        for r in rows:
            m = re.search(r"/(\d+)-", r.get("report", ""))
            if m:
                nums.append(int(m.group(1)))
        return (max(nums) + 1) if nums else 1


# --- rendering (module-level, pure) ---------------------------------------- #
def _render_table(rows: list[dict]) -> str:
    head = ("# Applications — master tracker\n\n"
            "| Date | Company | Role | Score | Status | Report |\n"
            "|------|---------|------|-------|--------|--------|\n")
    body = ""
    for r in rows:
        name = Path(r["report"]).name if r["report"] else ""
        link = f"[{name}]({r['report']})" if r["report"] else ""
        body += (f"| {r['date']} | {r['company']} | {r['role']} | "
                 f"{r.get('score','')} | {r.get('status','')} | {link} |\n")
    return head + body


def _render_pipeline(postings: list[JobPosting]) -> str:
    out = ["# Pipeline — discovered postings (inbox)\n"]
    for p in postings:
        salary = p.salary_text or (f"{p.salary_min}-{p.salary_max} {p.salary_currency}"
                                   if p.salary_min else "n/a")
        out.append(f"- **{p.title}** @ {p.company} — {p.location or 'n/a'} — {salary} "
                   f"([{p.source}]({p.url}))")
    return "\n".join(out) + "\n"


def _render_report(posting: JobPosting, ev: Evaluation) -> str:
    lines = [
        f"# {posting.title} @ {posting.company}",
        "",
        f"- **Source:** {posting.source}",
        f"- **Location:** {posting.location or 'n/a'}",
        f"- **Salary:** {posting.salary_text or 'n/a'}",
        f"- **URL:** {posting.url}",
        f"- **Overall:** {'' if ev.overall is None else ev.overall}/10",
        f"- **Verdict:** {ev.verdict or '(unscored)'}",
        f"- **Legitimacy:** {ev.legitimacy if ev.legitimacy is not None else 'n/a'}/10",
        "",
        "## Dimension scores",
        "",
        "| Dimension | Raw (0-10) | Evidence |",
        "|-----------|-----------|----------|",
    ]
    for d in ev.dimensions:
        evidence = d.evidence.replace("|", "\\|")
        lines.append(f"| {d.name} | {d.raw:g} | {evidence} |")
    lines += ["", "## Job description", "", (posting.description or "(not fetched)")]
    return "\n".join(lines) + "\n"

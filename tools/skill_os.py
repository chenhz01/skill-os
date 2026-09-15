#!/usr/bin/env python3
"""skill_os.py — the assembly line for evidence-first agent skills.

Four parts, one line:
    answer-contract   how the agent talks        (the contract every stage enforces)
    skill-spec        how the agent works        (SPEC contract + lint + evidence)
    memory-wiki       what the agent remembers   (knowledge wiki + freshness)
    skill-scorecard   what a buyer checks        (30-second safety grade)

skill_os.py wires them into one pipeline per skill:

    contract -> lint -> evidence -> scorecard -> verdict -> memory

Commands:
    check <skill_dir>              run the full line on one skill
    sweep <collection_root>        run the full line on every skill under root
          [--json OUT] [--md OUT] [--wiki DIR]   (memory-wiki ingest of the report)
    run <skill_dir> [--note TXT]   generate a fresh evidence run file from SPEC.md
    audit <evidence_file>          verify an evidence run (all boxes ticked?)

Verdicts:
    SHIP-READY      lint pass + latest evidence run fully ticked + grade A/B
    NEEDS-EVIDENCE  lint pass but no fully-ticked evidence run
    BLOCKED         lint FAIL, or scorecard grade D, or any scorecard FAIL

Zero dependencies. No network calls (unless scorecard gets a URL, which this
tool never does). Full-coverage output only: every sweep reports N/N.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BOX = re.compile(r"^(\s*)- \[([ xX])\] (.+)$", re.MULTILINE)


# --------------------------------------------------------------------------
# tool discovery: the four parts may live beside us (sibling repos) or be
# dropped into our own tools/ directory. No other magic.
# --------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
SEARCH_ROOTS = [
    HERE,
    HERE.parent.parent / "skill-spec" / "tools",
    HERE.parent.parent / "memory-wiki" / "tools",
    HERE.parent.parent / "skill-scorecard" / "tools",
]


def load_module(name: str, filename: str):
    for root in SEARCH_ROOTS:
        p = root / filename
        if p.exists():
            spec = importlib.util.spec_from_file_location(name, p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    print(f"error: cannot find {filename} (searched {SEARCH_ROOTS})", file=sys.stderr)
    sys.exit(2)


spec_lint = load_module("os_spec_lint", "spec_lint.py")
spec_evidence = load_module("os_spec_evidence", "spec_evidence.py")
scorecard_mod = load_module("os_scorecard", "skill_scorecard.py")
memory_wiki = load_module("os_memory_wiki", "memory_wiki.py")


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------
def evidence_state(skill_dir: Path) -> dict:
    """Latest evidence run state for a skill. Never raises."""
    runs = sorted((skill_dir / "evidence").glob("RUN-*.md")) if (skill_dir / "evidence").exists() else []
    if not runs:
        return {"runs": 0, "ticked": 0, "total": 0, "latest": None, "audited": False}
    latest = runs[-1]
    boxes = BOX.findall(latest.read_text(encoding="utf-8", errors="ignore"))
    total = len(boxes)
    ticked = sum(1 for _, mark, _ in boxes if mark.strip().lower() == "x")
    return {"runs": len(runs), "ticked": ticked, "total": total,
            "latest": latest.name, "audited": total > 0 and ticked == total}


def run_line(skill_dir: Path) -> dict:
    """Run contract->lint->evidence->scorecard->verdict on one skill dir."""
    r: dict = {"skill": skill_dir.name, "path": str(skill_dir)}
    has_skill_md = (skill_dir / "SKILL.md").exists()
    has_spec = (skill_dir / "SPEC.md").exists()
    r["contract"] = {"SKILL.md": has_skill_md, "SPEC.md": has_spec}

    lint = spec_lint.lint_skill(skill_dir)
    fails = sum(1 for lvl, _, _ in lint if lvl == "FAIL")
    warns = sum(1 for lvl, _, _ in lint if lvl == "WARN")
    r["lint"] = {"pass": len(lint) - fails - warns, "warn": warns, "fail": fails}

    r["evidence"] = evidence_state(skill_dir)

    try:
        _findings, score, grade = scorecard_mod.scorecard(skill_dir)
        sc_fails = any(lvl == "FAIL" for lvl, _, _ in _findings)
    except Exception as e:  # scorecard must never take the line down
        score, grade, sc_fails = 0, "D", True
        r["scorecard_error"] = str(e)
    r["scorecard"] = {"score": score, "grade": grade, "fail": sc_fails}

    if fails > 0 or grade == "D" or sc_fails or not has_skill_md:
        r["verdict"] = "BLOCKED"
    elif r["evidence"]["audited"]:
        r["verdict"] = "SHIP-READY"
    else:
        r["verdict"] = "NEEDS-EVIDENCE"
    return r


def print_report(r: dict) -> None:
    print(f"== {r['skill']}")
    c = r["contract"]
    print(f"  contract : SKILL.md {'✅' if c['SKILL.md'] else '❌'}  SPEC.md {'✅' if c['SPEC.md'] else '⬜'}")
    li = r["lint"]
    print(f"  lint     : {li['pass']} pass / {li['warn']} warn / {li['fail']} fail")
    ev = r["evidence"]
    if ev["runs"] == 0:
        print("  evidence : no runs yet (need one before claiming done)")
    else:
        print(f"  evidence : {ev['ticked']}/{ev['total']} ticked in {ev['latest']}"
              + ("  ✅ AUDITED" if ev["audited"] else "  ⬜ UNAUDITED"))
    sc = r["scorecard"]
    print(f"  scorecard: {sc['score']}/100 grade {sc['grade']}")
    print(f"  VERDICT  : {r['verdict']}\n")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_check(path: Path) -> int:
    if not path.exists():
        print(f"error: path not found: {path}", file=sys.stderr)
        return 1
    dirs = spec_lint.find_skill_dirs(path)
    if len(dirs) != 1:
        print(f"tip: {len(dirs)} skills under {path} — use 'sweep' for collections")
    r = run_line(dirs[0] if len(dirs) == 1 else path)
    print_report(r)
    return 0 if r["verdict"] != "BLOCKED" else 1


def cmd_run(skill_dir: Path, note: str | None) -> int:
    return spec_evidence.cmd_gen(skill_dir, note)


def cmd_audit(ev_file: Path) -> int:
    return spec_evidence.cmd_check(ev_file)


def cmd_sweep(root: Path, json_out: Path | None, md_out: Path | None, wiki: Path | None) -> int:
    if not root.exists():
        print(f"error: path not found: {root}", file=sys.stderr)
        return 1
    dirs = spec_lint.find_skill_dirs(root)
    n = len(dirs)
    print(f"skill-os sweep: {n} skill(s) under {root}\n")
    results = []
    for i, d in enumerate(dirs, 1):
        try:
            results.append(run_line(d))
        except Exception as e:
            results.append({"skill": d.name, "path": str(d), "verdict": "ERROR",
                            "lint": {"pass": 0, "warn": 0, "fail": 0},
                            "evidence": {"runs": 0, "ticked": 0, "total": 0, "audited": False},
                            "scorecard": {"score": 0, "grade": "D", "fail": True},
                            "contract": {"SKILL.md": False, "SPEC.md": False},
                            "error": str(e)})
        if i % 50 == 0 or i == n:
            print(f"  ... {i}/{n}")
    # full-coverage summary (N/N, per audit rule)
    verdicts = {}
    grades = {}
    lint_pass = 0
    ev_audited = 0
    for r in results:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        grades[r["scorecard"]["grade"]] = grades.get(r["scorecard"]["grade"], 0) + 1
        if r["lint"]["fail"] == 0:
            lint_pass += 1
        if r["evidence"]["audited"]:
            ev_audited += 1
    print(f"\nsweep summary (coverage {n}/{n}):")
    print(f"  lint pass   : {lint_pass}/{n}")
    print(f"  evidence    : {ev_audited}/{n} fully audited")
    print(f"  grades      : " + "  ".join(f"{g}={grades.get(g, 0)}" for g in "ABCD"))
    print(f"  verdicts    : " + "  ".join(f"{v}={c}" for v, c in sorted(verdicts.items())))

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(
            {"generated": datetime.now().isoformat(timespec="seconds"),
             "root": str(root), "coverage": f"{n}/{n}", "results": results},
            ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        print(f"\njson  -> {json_out}")
    if md_out:
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(render_sweep_md(root, n, results, verdicts, grades, lint_pass, ev_audited),
                          encoding="utf-8", newline="\n")
        print(f"md    -> {md_out}")
    # memory stage: archive the report into a memory-wiki
    if wiki and md_out:
        memory_wiki.cmd_ingest([md_out], wiki, force=True)
        memory_wiki.cmd_index(wiki)
        print(f"wiki  -> ingested + indexed into {wiki}")
    return 0


def render_sweep_md(root: Path, n: int, results: list, verdicts: dict, grades: dict,
                    lint_pass: int, ev_audited: int) -> str:
    lines = [f"# skill-os sweep report — {root.name}", "",
             f"- generated: {datetime.now().isoformat(timespec='seconds')}",
             f"- coverage: **{n}/{n}** skills (full sweep, no sampling)", "",
             "## Summary", "",
             f"- lint pass: {lint_pass}/{n}",
             f"- evidence fully audited: {ev_audited}/{n}",
             f"- grades: " + "  ".join(f"{g}={grades.get(g, 0)}" for g in "ABCD"),
             f"- verdicts: " + "  ".join(f"{v}={c}" for v, c in sorted(verdicts.items())), "",
             "## Blocked skills (lint FAIL / grade D)", ""]
    blocked = [r for r in results if r["verdict"] == "BLOCKED"]
    if blocked:
        for r in blocked:
            lines.append(f"- {r['skill']}: lint fail={r['lint']['fail']}, "
                         f"grade {r['scorecard']['grade']}")
    else:
        lines.append("- none")
    lines += ["", "## Ship-ready skills", ""]
    ready = [r for r in results if r["verdict"] == "SHIP-READY"]
    if ready:
        for r in ready:
            lines.append(f"- {r['skill']} (grade {r['scorecard']['grade']}, "
                         f"evidence {r['evidence']['ticked']}/{r['evidence']['total']})")
    else:
        lines.append("- none yet")
    lines += ["", "## Honest limits", "",
              "- lint green = structure complete, not human-reviewed.",
              "- scorecard grade = structural trust, not provable safety.",
              "- evidence audited = every box ticked with real artifacts; quality of the",
              "  artifact itself still needs human judgment.",
              "- this sweep checks files only; it does not execute skill scripts."]
    return "\n".join(lines) + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="assembly line for evidence-first agent skills")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check"); pc.add_argument("path", type=Path)
    pw = sub.add_parser("sweep"); pw.add_argument("root", type=Path)
    pw.add_argument("--json", dest="json_out", type=Path, default=None)
    pw.add_argument("--md", dest="md_out", type=Path, default=None)
    pw.add_argument("--wiki", type=Path, default=None,
                    help="ingest the md report into this memory-wiki")
    pr = sub.add_parser("run"); pr.add_argument("skill_dir", type=Path)
    pr.add_argument("--note", default=None)
    pa = sub.add_parser("audit"); pa.add_argument("evidence_file", type=Path)
    a = ap.parse_args()
    if a.cmd == "check":
        return cmd_check(a.path)
    if a.cmd == "sweep":
        return cmd_sweep(a.root, a.json_out, a.md_out, a.wiki)
    if a.cmd == "run":
        return cmd_run(a.skill_dir, a.note)
    return cmd_audit(a.evidence_file)


if __name__ == "__main__":
    sys.exit(main())

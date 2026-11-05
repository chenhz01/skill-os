#!/usr/bin/env python3
"""spec_evidence.py — the black box for AI agent skills.

A skill with a SPEC.md has a contract. This tool turns that contract into
per-run evidence: before executing a skill, generate a run file with its
acceptance checklist; after executing, the agent (or the human) ticks each
item with real evidence; `check` refuses to pass until every item is ticked.

A skill execution without evidence is unaudited. This is the flight recorder:
not a quality guarantee — a truth guarantee about what was checked.

Commands:
    gen   <skill_dir> [--note "context"]   write evidence/RUN-<stamp>.md from SPEC.md
    check <evidence_file>                  exit 0 only when every item is ticked

Zero dependencies. Plain markdown.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ACC_START = re.compile(r"^##\s*4\.?\s*acceptance\b|^##\s*4\.?\s*验收", re.IGNORECASE | re.MULTILINE)
NEXT_H2 = re.compile(r"^##\s", re.MULTILINE)
BOX = re.compile(r"^(\s*)- \[([ xX])\] (.+)$", re.MULTILINE)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def acceptance_items(spec_text: str) -> list[str]:
    m = ACC_START.search(spec_text)
    if not m:
        return []
    rest = spec_text[m.end():]
    n = NEXT_H2.search(rest)
    section = rest[: n.start()] if n else rest
    return [text for _, _, text in BOX.findall(section)]


def cmd_gen(skill_dir: Path, note: str | None) -> int:
    spec = skill_dir / "SPEC.md"
    if not spec.exists():
        print(f"no SPEC.md under {skill_dir}")
        return 1
    items = acceptance_items(read(spec))
    if not items:
        print(f"no acceptance checkboxes found in {spec}")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ev_dir = skill_dir / "evidence"
    ev_dir.mkdir(exist_ok=True)
    out = ev_dir / f"RUN-{stamp}.md"
    lines = [
        f"# Evidence: {skill_dir.name} — RUN-{stamp}",
        "",
        f"- run id: RUN-{stamp}",
        f"- generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- skill: {skill_dir.name}",
    ]
    if note:
        lines.append(f"- note: {note}")
    lines += ["", "> Tick an item only with real evidence (command output, file path, N/N count).",
              "> `check` fails until every box is ticked.", "", "## Acceptance checklist", ""]
    lines += [f"- [ ] {it}" for it in items]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"WROTE {out} ({len(items)} unchecked item(s))")
    return 0


def cmd_check(ev_file: Path) -> int:
    if not ev_file.exists():
        print(f"no such evidence file: {ev_file}")
        return 1
    text = read(ev_file)
    boxes = BOX.findall(text)
    if not boxes:
        print("no checklist items found in evidence file")
        return 1
    done = [(mark, item) for _, mark, item in boxes]
    unchecked = [item for mark, item in done if mark.strip().lower() != "x"]
    for mark, item in done:
        print(f"  {'✅' if mark.strip().lower() == 'x' else '⬜'} {item}")
    total = len(done)
    print(f"\ncheck: {total - len(unchecked)}/{total} ticked")
    if unchecked:
        print("VERDICT: UNAUDITED — tick every item with real evidence before claiming done")
        return 1
    print("VERDICT: AUDITED — every acceptance item carries a tick")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="per-run evidence from a skill's SPEC acceptance checklist")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pg = sub.add_parser("gen")
    pg.add_argument("skill_dir", type=Path)
    pg.add_argument("--note", default=None, help="one-line context for this run")
    pc = sub.add_parser("check")
    pc.add_argument("evidence_file", type=Path)
    a = ap.parse_args()
    if a.cmd == "gen":
        return cmd_gen(a.skill_dir, a.note)
    return cmd_check(a.evidence_file)


if __name__ == "__main__":
    sys.exit(main())

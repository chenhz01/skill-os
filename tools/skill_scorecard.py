#!/usr/bin/env python3
"""skill_scorecard.py — a 30-second safety scorecard for AI agent skills.

GitHub's own docs warn that third-party agent skills may contain prompt
injections, hidden instructions, or malicious scripts. This tool gives any
skill folder (local, or a GitHub repo URL) a structured scorecard before you
install it: contract, license, risk signals, size, provenance.

It cannot read minds — it reads structure. A passing grade is not a safety
guarantee; a failing grade is a reason to read the skill yourself.

Usage:
    python skill_scorecard.py path/to/skill/
    python skill_scorecard.py https://github.com/owner/repo

Zero third-party dependencies (stdlib only).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

MAX_LINES = 200
INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", "prompt-injection phrase"),
    (r"disregard\s+(all\s+)?(previous|prior|above)", "prompt-injection phrase"),
    (r"exfiltrat(e|ion)", "exfiltration language"),
    (r"(curl|wget|requests\.|urllib).*(post|upload|send)", "network exfil call"),
]
B64_RE = re.compile(r"[A-Za-z0-9+/=]{300,}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def fetch_github(url: str) -> Path:
    """Download a GitHub repo tarball to a temp dir; return its root."""
    m = re.match(r"https?://github\.com/([\w.-]+)/([\w.-]+)/?", url.rstrip("/"))
    if not m:
        raise ValueError(f"not a GitHub repo URL: {url}")
    owner, repo = m.group(1), m.group(2)
    base = f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/heads"
    for branch in ("main", "master"):
        try:
            with urllib.request.urlopen(f"{base}/{branch}", timeout=60) as r:
                data = r.read()
            break
        except Exception:
            data = None
    if not data:
        raise RuntimeError(f"could not download {owner}/{repo} (main/master)")
    tmp = Path(tempfile.mkdtemp(prefix="scorecard-"))
    tgz = tmp / "repo.tgz"
    tgz.write_bytes(data)
    import tarfile
    with tarfile.open(tgz) as tf:
        tf.extractall(tmp)  # noqa: S202 - trusted source chosen by the user
    tgz.unlink()
    roots = [d for d in tmp.iterdir() if d.is_dir()]
    return roots[0] if roots else tmp


def scorecard(skill: Path) -> tuple[list[tuple[str, str, str]], int, str]:
    """Return (findings, score, grade)."""
    findings: list[tuple[str, str, str]] = []  # (level, check, detail)

    sm = skill / "SKILL.md"
    if not sm.exists():
        findings.append(("FAIL", "SKILL.md present", "missing — not a skill folder"))
        return finish(findings)
    text = read(sm)

    # frontmatter
    fm = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not fm:
        findings.append(("FAIL", "YAML frontmatter", "missing — no name/description metadata"))
    else:
        block = fm.group(1)
        missing = [k for k in ("name:", "description:") if k not in block]
        if missing:
            findings.append(("FAIL", "frontmatter fields", f"missing {', '.join(missing)}"))
        else:
            findings.append(("PASS", "frontmatter", "name + description present"))

    # SPEC
    if (skill / "SPEC.md").exists():
        findings.append(("PASS", "SPEC contract", "SPEC.md present"))
    else:
        findings.append(("WARN", "SPEC contract", "no SPEC.md — behavior is unaudited against a contract"))

    # license
    has_license = any((skill / f).exists() for f in
                      ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"))
    if has_license:
        findings.append(("PASS", "license", "present"))
    else:
        findings.append(("WARN", "license", "missing — usage terms unknown"))

    # scripts/ risk signal (research: odds ratio 2.12 for defects)
    scripts = skill / "scripts"
    if scripts.exists():
        findings.append(("WARN", "scripts/ directory",
                         "present — code the agent may run; read it before installing (2.12x defect odds in marketplace samples)"))
    else:
        findings.append(("PASS", "scripts/ directory", "none — instructions only"))

    # hidden instruction scan
    scan_targets = [text] + [read(f) for f in scripts.glob("*") if f.is_file()] if scripts.exists() else [text]
    blob_found = any(B64_RE.search(t) for t in scan_targets)
    if blob_found:
        findings.append(("WARN", "hidden content", "very long opaque blob (possible encoded payload) — inspect manually"))
    else:
        findings.append(("PASS", "hidden content", "no opaque blobs"))
    for t in scan_targets:
        for pat, label in INJECTION_PATTERNS:
            if re.search(pat, t, re.IGNORECASE):
                findings.append(("FAIL", "injection scan", f"{label}: /{pat[:28]}.../ matched"))
                break

    # size
    n_lines = len(text.splitlines())
    if n_lines > MAX_LINES:
        findings.append(("WARN", "size", f"SKILL.md is {n_lines} lines (>{MAX_LINES}) — adherence decays with length"))
    else:
        findings.append(("PASS", "size", f"{n_lines} lines"))

    return finish(findings)


def finish(findings: list[tuple[str, str, str]]) -> tuple[list[tuple[str, str, str]], int, str]:
    score = 100
    for lvl, _, _ in findings:
        if lvl == "FAIL":
            score -= 30
        elif lvl == "WARN":
            score -= 10
    grade = "A" if score >= 90 else "B" if score >= 70 else "C" if score >= 50 else "D"
    return findings, score, grade


def render(name: str, findings: list[tuple[str, str, str]], score: int, grade: str) -> str:
    mark = {"PASS": "✅", "WARN": "🟡", "FAIL": "❌"}
    lines = [f"# Skill scorecard: {name}", "",
             f"**Score: {score}/100 — Grade {grade}**", "",
             "A grade means structurally trustworthy, not provably safe. Read before you install.", ""]
    for lvl, check, detail in findings:
        lines.append(f"- {mark[lvl]} **{check}** — {detail}")
    return "\n".join(lines) + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="30-second safety scorecard for AI agent skills")
    ap.add_argument("target", help="local skill directory or GitHub repo URL")
    a = ap.parse_args()

    if a.target.startswith("http"):
        print(f"fetching {a.target} ...")
        try:
            skill = fetch_github(a.target)
        except Exception as e:
            print(f"fetch failed: {e}")
            return 1
    else:
        skill = Path(a.target)
        if not skill.is_dir():
            print(f"not a directory: {skill}")
            return 1

    findings, score, grade = scorecard(skill)
    print(render(skill.name, findings, score, grade))
    if not (skill / "SKILL.md").exists():
        nested = [str(p.relative_to(skill).parent) for p in skill.rglob("SKILL.md")][:3]
        if nested:
            print("\nnote: no SKILL.md at repo root — this looks like a skill *collection*.")
            print(f"score a subfolder instead, e.g. one of: {', '.join(nested)}")
    return 1 if any(lvl == "FAIL" for lvl, _, _ in findings) else 0


if __name__ == "__main__":
    sys.exit(main())

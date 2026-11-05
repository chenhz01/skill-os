#!/usr/bin/env python3
"""spec_lint.py — contract linter for AI agent skill folders.

Scans directories containing SKILL.md and checks for a spec-discipline contract:
frontmatter completeness, SPEC.md presence, six required sections, falsifiable
acceptance criteria, and honest limits.

Usage:
    python spec_lint.py <path>          # one skill dir, or a collection dir
    python spec_lint.py <path> --strict # warnings become failures

Exit codes: 0 = all pass (warnings allowed), 1 = at least one FAIL.
Zero dependencies. No network calls.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = [
    ("purpose", [r"^##\s*1\.?\s*purpose\b", r"^##\s*1\.?\s*目的"]),
    ("interface", [r"^##\s*2\.?\s*interface\b", r"^##\s*2\.?\s*(?:输入|接口)"]),
    ("procedure", [r"^##\s*3\.?\s*procedure\b", r"^##\s*3\.?\s*(?:流程|步骤)"]),
    ("acceptance", [r"^##\s*4\.?\s*acceptance\b", r"^##\s*4\.?\s*验收"]),
    ("guards", [r"^##\s*5\.?\s*guards\b", r"^##\s*5\.?\s*(?:护栏|红线)"]),
    ("honest limits", [r"^##\s*6\.?\s*honest\s+limits\b", r"^##\s*6\.?\s*[^\n:：]*局限", r"^##\s*6\.?\s*诚实"]),
]

# Vague phrasing that must NOT appear in the Acceptance section
VAGUE_PATTERNS = [
    r"\bworks well\b",
    r"\blooks good\b",
    r"\buser[- ]friendly\b",
    r"\bhigh quality\b",
    r"\bas needed\b",
]

FALSIFIABLE_SIGNALS = [
    r"\[\s*[ x]\s*\]",      # checkboxes
    r"\b\d+\s*/\s*\d+\b",   # N/N coverage
    r"[<>≤≥]=?\s*\d",       # quantified thresholds
    r"\bexit code\b",
    r"\bmust match\b",
    r"\bshall return\b",
]


def has_frontmatter(skill_md: str) -> tuple[bool, list[str]]:
    """Return (ok, missing_fields) for a SKILL.md YAML-ish frontmatter."""
    m = re.match(r"^---\s*\n(.*?)\n---", skill_md, re.DOTALL)
    if not m:
        return False, ["frontmatter block (--- ... ---)"]
    fm = m.group(1)
    missing = [f for f in ("name", "description") if not re.search(rf"^{f}\s*:", fm, re.MULTILINE)]
    return not missing, missing


def find_section(spec: str, patterns: list[str]):
    """Return the first matching section match object (header + body), or None."""
    for p in patterns:
        m = re.search(rf"{p}(.*?)(?=^##\s|\Z)", spec,
                      re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if m:
            return m
    return None


def lint_skill(skill_dir: Path) -> list[tuple[str, str, str]]:
    """Lint one skill directory. Returns list of (level, check, detail)."""
    results: list[tuple[str, str, str]] = []
    skill_md_path = skill_dir / "SKILL.md"
    spec_md_path = skill_dir / "SPEC.md"

    # 1. SKILL.md + frontmatter
    if not skill_md_path.exists():
        return [("FAIL", "SKILL.md exists", f"{skill_dir} has no SKILL.md")]
    skill_md = skill_md_path.read_text(encoding="utf-8", errors="ignore")
    ok, missing = has_frontmatter(skill_md)
    results.append(
        ("PASS" if ok else "FAIL", "frontmatter name/description",
         "complete" if ok else f"missing {', '.join(missing)}"))

    # 2. SPEC.md presence
    if not spec_md_path.exists():
        results.append(("WARN", "SPEC.md exists",
                        "missing — copy SPEC_TEMPLATE.md next to SKILL.md to add one"))
        return results
    spec = spec_md_path.read_text(encoding="utf-8", errors="ignore")

    # 3. Six required sections (English or Chinese headers)
    for name, patterns in REQUIRED_SECTIONS:
        found = any(re.search(p, spec, re.IGNORECASE | re.MULTILINE) for p in patterns)
        results.append(("PASS" if found else "FAIL", f"section: {name}",
                        "present" if found else "absent"))

    # 4. Falsifiable acceptance criteria
    acc = find_section(spec, dict(REQUIRED_SECTIONS)["acceptance"])
    if acc:
        body = acc.group(1)
        if any(re.search(p, body, re.IGNORECASE) for p in VAGUE_PATTERNS):
            results.append(("FAIL", "falsifiable acceptance",
                            "contains vague phrasing (works well / looks good / high quality / as needed)"))
        elif any(re.search(p, body) for p in FALSIFIABLE_SIGNALS):
            results.append(("PASS", "falsifiable acceptance",
                            "checkboxes / N-N coverage / quantified threshold found"))
        else:
            results.append(("WARN", "falsifiable acceptance",
                            "no checkboxes, N/N coverage, or quantified threshold detected"))
    # covered by section check if absent

    # 5. Honest limits non-empty
    hl = find_section(spec, dict(REQUIRED_SECTIONS)["honest limits"])
    if hl:
        body = hl.group(1).strip()
        results.append(("PASS" if len(body) > 40 else "WARN", "honest limits non-empty",
                        f"{len(body)} chars" if body else "empty"))

    return results


def find_skill_dirs(root: Path) -> list[Path]:
    if (root / "SKILL.md").exists():
        return [root]
    return sorted(p.parent for p in root.rglob("SKILL.md"))


def main() -> int:
    ap = argparse.ArgumentParser(description="spec-discipline linter for agent skill folders")
    ap.add_argument("path", type=Path, help="a skill directory or a collection directory")
    ap.add_argument("--strict", action="store_true", help="treat WARN as FAIL")
    args = ap.parse_args()

    if not args.path.exists():
        print(f"error: path not found: {args.path}", file=sys.stderr)
        return 1

    skill_dirs = find_skill_dirs(args.path)
    if not skill_dirs:
        print(f"no SKILL.md found under {args.path}")
        return 1

    failed_skills = warned_skills = 0
    print(f"spec-lint: {len(skill_dirs)} skill(s) under {args.path}\n")
    for d in skill_dirs:
        label = d.name if d != args.path else str(d)
        print(f"== {label}")
        skill_failed = skill_warned = False
        for level, check, detail in lint_skill(d):
            mark = {"PASS": "✅", "WARN": "🟡", "FAIL": "❌"}[level]
            print(f"  {mark} [{level}] {check}: {detail}")
            if level == "FAIL" or (level == "WARN" and args.strict):
                skill_failed = True
            elif level == "WARN":
                skill_warned = True
        if skill_failed:
            failed_skills += 1
        elif skill_warned:
            warned_skills += 1
        print()

    total = len(skill_dirs)
    passing = total - failed_skills
    print(f"summary: {passing}/{total} skill(s) pass"
          + (f", {warned_skills} with warnings" if warned_skills else "")
          + (f", {failed_skills} failing" if failed_skills else ""))
    return 1 if failed_skills else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""memory_wiki.py — a file-layer wiki for your agent's markdown memory.

Your agent accumulates memory as scattered markdown: daily logs, memory files,
notes. Databases and servers are overkill. This tool turns a folder of markdown
into a small wiki: entries are absorbed and registered, an index is generated,
queries run with plain keyword ranking, and lint catches rot (orphans, missing
dates, duplicate titles, overlong files).

Commands:
    ingest <files...> --wiki <dir>   absorb markdown files as wiki entries
    index  --wiki <dir>              rebuild the wiki's index.md
    query  <terms...> --wiki <dir>   keyword search across entries (ranked)
    lint   --wiki <dir>              health check: rot report, exit 1 on FAIL
    fresh  --wiki <dir>              freshness report: fresh / stale / rotten / undated
    refresh <entries...> --wiki <dir> mark entries as re-verified today (closes the loop)
    log    --wiki <dir>              show the operation log

Zero dependencies. No server. Plain markdown. Everything stays on your disk.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ENTRIES = "entries"
MAX_LINES = 400
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
LV_RE = re.compile(r"last-verified:\s*(20\d{2}-\d{2}-\d{2})")


def slugify(path: Path) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", path.stem).strip("-").lower()
    return slug or "entry"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def wiki_paths(wiki: Path) -> tuple[Path, Path, Path, Path]:
    return (wiki, wiki / "index.md", wiki / "log.md", wiki / ENTRIES)


def entry_stats(p: Path) -> dict:
    text = read(p)
    lines = text.splitlines()
    lv_m = LV_RE.search(text[:400])
    d_m = None if lv_m else DATE_RE.search(text[:400])
    title_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    first = next((l.strip() for l in lines if l.strip() and not l.startswith("#")), "")
    return {
        "path": p, "title": (title_m.group(1).strip() if title_m else p.stem),
        # effective date: last-verified wins over the original date — a refreshed
        # entry is as fresh as its verification, not its birth
        "date": (lv_m.group(1) if lv_m else (d_m.group(1) if d_m else "")),
        "verified": bool(lv_m), "lines": len(lines),
        "first": first[:100], "text": text,
    }


def append_log(wiki: Path, line: str) -> None:
    _, _, log, _ = wiki_paths(wiki)
    with log.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"{date.today().isoformat()} {line}\n")


def cmd_ingest(files: list[Path], wiki: Path, force: bool) -> int:
    _, _, _, edir = wiki_paths(wiki)
    edir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files:
        if not f.exists() or f.suffix.lower() not in (".md", ".markdown"):
            print(f"  SKIP {f} (not found or not markdown)")
            continue
        target = edir / f"{slugify(f)}.md"
        if target.exists() and not force:
            print(f"  SKIP {target.name} (entry exists; --force to replace)")
            continue
        text = read(f)
        if not DATE_RE.search(text[:400]):
            text = f"---\ningested: {date.today().isoformat()}\nsource: {f.name}\n---\n\n" + text
        target.write_text(text, encoding="utf-8", newline="\n")
        append_log(wiki, f"INGEST {f.name} -> {target.name}")
        print(f"  WROTE {target.name}")
        n += 1
    cmd_index(wiki)
    print(f"ingested {n} file(s); index rebuilt")
    return 0


def cmd_index(wiki: Path) -> int:
    _, index, _, edir = wiki_paths(wiki)
    if not edir.exists():
        print(f"no {ENTRIES}/ under {wiki}")
        return 1
    rows = sorted((entry_stats(p) for p in edir.glob("*.md")), key=lambda s: (s["date"], s["path"].name), reverse=True)
    out = ["# Index", "", "| entry | date | last verified | first line |", "|---|---|---|---|"]
    for s in rows:
        rel = f"{ENTRIES}/{s['path'].name}"
        lv = "✓" if s["verified"] else "—"
        out.append(f"| [{s['title']}]({rel}) | {s['date'] or '—'} | {lv} | {s['first'] or '—'} |")
    index.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"index rebuilt: {len(rows)} entr(y|ies) -> {index}")
    return 0


def cmd_query(terms: list[str], wiki: Path) -> int:
    _, _, _, edir = wiki_paths(wiki)
    if not edir.exists():
        print(f"no {ENTRIES}/ under {wiki}")
        return 1
    scored = []
    for p in edir.glob("*.md"):
        text = read(p)
        score = sum(text.lower().count(t.lower()) for t in terms)
        if score:
            hits = [l.strip() for l in text.splitlines() if any(t.lower() in l.lower() for t in terms)][:3]
            scored.append((score, p, hits))
    if not scored:
        print("no matches")
        return 0
    for score, p, hits in sorted(scored, reverse=True, key=lambda x: x[0]):
        print(f"[{score} hits] {ENTRIES}/{p.name}")
        for h in hits:
            print(f"    > {h[:120]}")
    return 0


def cmd_lint(wiki: Path) -> int:
    _, index, _, edir = wiki_paths(wiki)
    problems: list[tuple[str, str]] = []
    entries = sorted(edir.glob("*.md")) if edir.exists() else []
    if not entries:
        print(f"no entries under {wiki}")
        return 1
    titles: dict[str, int] = {}
    for p in entries:
        s = entry_stats(p)
        titles[s["title"]] = titles.get(s["title"], 0) + 1
        if not s["date"]:
            problems.append(("WARN", f"{p.name}: no date in first 400 chars"))
        if s["lines"] > MAX_LINES:
            problems.append(("WARN", f"{p.name}: {s['lines']} lines (>{MAX_LINES}) — consider splitting"))
    for t, c in titles.items():
        if c > 1:
            problems.append(("FAIL", f"duplicate title x{c}: {t}"))
    idx = read(index) if index.exists() else ""
    for p in entries:
        if p.name not in idx:
            problems.append(("FAIL", f"{p.name}: not in index.md (orphan)"))
    # broken relative links in entries
    for p in entries:
        for m in re.finditer(r"\]\((?!http)([^)#]+)\)", read(p)):
            link = m.group(1).strip()
            if not (p.parent / link).exists():
                problems.append(("WARN", f"{p.name}: broken relative link -> {link}"))
    fails = sum(1 for lvl, _ in problems if lvl == "FAIL")
    for lvl, msg in problems:
        print(f"  {'❌' if lvl == 'FAIL' else '🟡'} [{lvl}] {msg}")
    print(f"\nlint: {len(entries)} entries, {len(problems)} problem(s) ({fails} FAIL)")
    return 1 if fails else 0


def cmd_fresh(wiki: Path, max_age: int, rot_age: int) -> int:
    """Freshness report: entries classified by effective date age."""
    _, _, _, edir = wiki_paths(wiki)
    if not edir.exists():
        print(f"no {ENTRIES}/ under {wiki}")
        return 1
    today = date.today()
    buckets: dict[str, list[str]] = {"fresh": [], "stale": [], "rotten": [], "undated": []}
    for p in sorted(edir.glob("*.md")):
        s = entry_stats(p)
        if not s["date"]:
            buckets["undated"].append(p.name)
            continue
        age = (today - date.fromisoformat(s["date"])).days
        if age > rot_age:
            buckets["rotten"].append(f"{p.name} ({age}d)")
        elif age > max_age:
            buckets["stale"].append(f"{p.name} ({age}d)")
        else:
            buckets["fresh"].append(f"{p.name} ({age}d)")
    mark = {"fresh": "✅", "stale": "🟡", "rotten": "🧟", "undated": "❓"}
    for k in ("rotten", "stale", "undated", "fresh"):
        items = buckets[k]
        print(f"{mark[k]} [{k}] {len(items)}")
        for it in items:
            print(f"    - {it}")
    total = sum(len(v) for v in buckets.values())
    print(f"\nfresh: {total} entries — {len(buckets['fresh'])} fresh, "
          f"{len(buckets['stale'])} stale, {len(buckets['rotten'])} rotten, "
          f"{len(buckets['undated'])} undated")
    print("next step: re-check the rotten ones, then run `refresh` on them")
    return 1 if buckets["rotten"] else 0


def cmd_refresh(names: list[str], wiki: Path) -> int:
    """Mark entries as re-verified today: the loop-closing half of `fresh`."""
    _, _, _, edir = wiki_paths(wiki)
    if not edir.exists():
        print(f"no {ENTRIES}/ under {wiki}")
        return 1
    today = date.today().isoformat()
    n = 0
    for name in names:
        p = edir / (name if name.endswith(".md") else f"{name}.md")
        if not p.exists():
            print(f"  SKIP {name} (no such entry)")
            continue
        text = read(p)
        if "last-verified:" in text:
            text = re.sub(r"last-verified:\s*20\d{2}-\d{2}-\d{2}", f"last-verified: {today}", text)
        elif text.startswith("---"):
            end = text.index("---", 3) + 3
            text = text[:end] + f"\nlast-verified: {today}" + text[end:]
        else:
            text = f"---\nlast-verified: {today}\n---\n\n" + text
        p.write_text(text, encoding="utf-8", newline="\n")
        append_log(wiki, f"REFRESH {p.name} (last-verified: {today})")
        print(f"  REFRESHED {p.name}")
        n += 1
    cmd_index(wiki)
    print(f"refreshed {n} entry(ies); index rebuilt")
    return 0


def cmd_log(wiki: Path, tail: int) -> int:
    _, _, log, _ = wiki_paths(wiki)
    if not log.exists():
        print("log is empty")
        return 0
    lines = read(log).splitlines()
    for l in lines[-tail:]:
        print(l)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="file-layer wiki for agent markdown memory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add_wiki(p):
        p.add_argument("--wiki", type=Path, default=Path("wiki"), help="wiki directory (default: ./wiki)")
    pi = sub.add_parser("ingest"); pi.add_argument("files", nargs="+", type=Path); pi.add_argument("--force", action="store_true"); add_wiki(pi)
    px = sub.add_parser("index"); add_wiki(px)
    pq = sub.add_parser("query"); pq.add_argument("terms", nargs="+"); add_wiki(pq)
    pl2 = sub.add_parser("lint"); add_wiki(pl2)
    pf = sub.add_parser("fresh"); pf.add_argument("--max-age", type=int, default=30, help="days before an entry counts as stale (default: 30)"); pf.add_argument("--rot-age", type=int, default=90, help="days before an entry counts as rotten (default: 90)"); add_wiki(pf)
    pr = sub.add_parser("refresh"); pr.add_argument("names", nargs="+", help="entry file names (with or without .md)"); add_wiki(pr)
    pl = sub.add_parser("log"); pl.add_argument("--tail", type=int, default=20); add_wiki(pl)
    a = ap.parse_args()

    if a.cmd == "ingest":
        return cmd_ingest(a.files, a.wiki, a.force)
    if a.cmd == "index":
        return cmd_index(a.wiki)
    if a.cmd == "query":
        return cmd_query(a.terms, a.wiki)
    if a.cmd == "lint":
        return cmd_lint(a.wiki)
    if a.cmd == "fresh":
        return cmd_fresh(a.wiki, a.max_age, a.rot_age)
    if a.cmd == "refresh":
        return cmd_refresh(a.names, a.wiki)
    if a.cmd == "log":
        return cmd_log(a.wiki, a.tail)
    return 1


if __name__ == "__main__":
    sys.exit(main())

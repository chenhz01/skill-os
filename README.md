# skill-os

> **Part of the Evidence-first Agents suite** — tooling that makes AI agents
> accountable instead of just capable: [answer-contract](https://github.com/chenhz01/answer-contract)
> (output discipline) · [skill-spec](https://github.com/chenhz01/skill-spec)
> (spec discipline) · [skill-scorecard](https://github.com/chenhz01/skill-scorecard)
> (buyer-side grading) · [memory-wiki](https://github.com/chenhz01/memory-wiki)
> (memory discipline). skill-os is the assembly line that wires all four into one pipeline.

**The assembly line for evidence-first agent skills.** Four single-file tools, one pipeline. Battle-tested on a 482-skill internal library (full sweeps, N/N coverage, no sampling).

| Stage | Tool | Repo | Question it answers |
|---|---|---|---|
| 0 contract | answer-contract | [chenhz01/answer-contract](https://github.com/chenhz01/answer-contract) | How should the agent *talk*? |
| 1–2 spec | skill-spec | [chenhz01/skill-spec](https://github.com/chenhz01/skill-spec) | How does the agent *work*, and what proves it ran? |
| 3 grade | skill-scorecard | [chenhz01/skill-scorecard](https://github.com/chenhz01/skill-scorecard) | Is this skill safe to *install*? |
| 4 memory | memory-wiki | [chenhz01/memory-wiki](https://github.com/chenhz01/memory-wiki) | What did the agent *learn*, and is it still fresh? |

skill_os.py wires them into one line per skill:

```
contract -> lint -> evidence -> scorecard -> verdict -> memory
```

## Commands

```bash
python tools/skill_os.py check <skill_dir>          # full line on one skill
python tools/skill_os.py sweep <library> --md r.md --wiki wiki/   # full coverage N/N
python tools/skill_os.py run <skill_dir> --note ""  # generate evidence run file
python tools/skill_os.py audit <evidence_file>      # all boxes ticked?
```

## Verdicts

- **BLOCKED** — lint FAIL, or grade D, or any scorecard FAIL. Do not ship.
- **NEEDS-EVIDENCE** — structure fine, but no fully-ticked evidence run. Don't claim done.
- **SHIP-READY** — lint pass + latest evidence run fully ticked + grade A/B.

## First external audit

**[obra/superpowers](https://github.com/obra/superpowers)** — a popular real-world skill collection, audited with `sweep` on 2026-09-16 (snapshot `b36e0829c6d0`, full coverage 14/14, no sampling):

| Check | Result |
|---|---|
| lint (structure) | **14/14 pass** |
| evidence (audit runs) | **0/14** fully audited |
| scorecard grades | A=0 · B=12 · C=2 · D=0 |
| verdicts | NEEDS-EVIDENCE=14 · BLOCKED=0 |

Honest reading: superpowers is structurally clean — every skill lints, nothing blocked, nothing graded D. The two C grades (`brainstorming`, `subagent-driven-development`) bundle a `scripts/` directory without a license file or SPEC. And none of the 14 carries per-run evidence — exactly the gap this assembly line exists to close: a clean-looking skill and an *audited* skill are not the same thing.

## Tool discovery

skill_os.py looks for the four tool files beside itself (sibling repos layout) or
dropped into its own `tools/` directory. Zero dependencies, Python 3.10+ stdlib only.

## Honest limits

- lint green = structure complete, not human-reviewed.
- Grade A = structurally trustworthy, not provably safe.
- Evidence audited = every box ticked with real artifacts; artifact quality still needs judgment.
- The sweep reads files only; it never executes skill scripts.

## License

MIT

<a href="https://github.com/chenhz01/skill-os">canary: CANARY-ZS-OS-20260916-7BB0CD86</a>

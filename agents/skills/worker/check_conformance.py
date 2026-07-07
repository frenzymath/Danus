#!/usr/bin/env python3
"""Conformance check for the worker proving skills.

Asserts, for every skill folder next to this script:
  1. SKILL.md exists and opens with a valid YAML frontmatter block
     (`---` ... `---`) carrying at least `name` and `description`.
  2. The frontmatter `name` equals the folder name.
  3. The SKILL.md body references no main-only gateway tool.

This is a cheap guard so no SKILL.md drifts to a main-only tool (e.g.
`fact_revoke`) or a nonexistent tool. It is not a runtime dependency; run it
after editing a skill.

Exit 0 = all skills conform; exit 1 = at least one problem (printed).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The nine installable skill folders.
SKILLS = [
    "query-memory",
    "search-math-results",
    "obtain-immediate-conclusions",
    "construct-toy-examples",
    "construct-counterexamples",
    "propose-subgoal-decomposition-plans",
    "direct-proving",
    "identify-key-failures",
    "verify-proof",
]

# Gateway tools a worker must NOT reference (main-only / not in the worker role).
FORBIDDEN_GATEWAY_TOOLS = {
    "fact_revoke",
}

# Pattern for a `foo_bar(` style tool invocation mentioned in prose/backticks.
TOOL_CALL_RE = re.compile(r"`?([a-z][a-z0-9_]*)\s*\(")


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return {name, description, ...} from a leading `---`...`---` block, or None."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end].strip("\n")
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields


def check_skill(folder: str) -> list[str]:
    problems: list[str] = []
    skill_dir = HERE / folder
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{folder}: SKILL.md missing"]

    text = skill_md.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm is None:
        problems.append(f"{folder}: no valid YAML frontmatter block")
        return problems
    if "name" not in fm:
        problems.append(f"{folder}: frontmatter missing `name`")
    elif fm["name"] != folder:
        problems.append(f"{folder}: frontmatter name {fm['name']!r} != folder name")
    if not fm.get("description"):
        problems.append(f"{folder}: frontmatter missing `description`")

    # Body after the frontmatter.
    end = text.find("\n---", 3)
    body = text[end + 4:] if end != -1 else text

    for token in set(TOOL_CALL_RE.findall(body)):
        if token in FORBIDDEN_GATEWAY_TOOLS:
            problems.append(
                f"{folder}: references forbidden (main-only) tool {token!r}"
            )
    return problems


def main() -> int:
    all_problems: list[str] = []
    for folder in SKILLS:
        all_problems.extend(check_skill(folder))
    # Also flag any skill folder present on disk but not in the expected list.
    on_disk = {
        p.name
        for p in HERE.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    }
    for extra in sorted(on_disk - set(SKILLS)):
        all_problems.append(f"{extra}: unexpected skill folder (not in the 9)")
    for missing in sorted(set(SKILLS) - on_disk):
        all_problems.append(f"{missing}: expected skill folder missing")

    if all_problems:
        print("CONFORMANCE FAILED:")
        for p in all_problems:
            print(f"  - {p}")
        return 1
    print(f"OK: all {len(SKILLS)} worker skills conform "
          f"(frontmatter valid, name==folder, no main-only tools).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

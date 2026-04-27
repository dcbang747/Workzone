#!/usr/bin/env python3
"""
Extend the two CK3 MAA effects in effects_to_change.txt so they encompass
every Men-At-Arms type defined across the lotr_*_regiment_types.txt files.

For each MAA block found in any regiment file:
  - Skip it if can_recruit is `always = no`.
  - Pull the cultural trigger(s) out of can_recruit:
        culture = { has_innovation        = X }
        culture = { has_cultural_tradition = X }
        culture = { has_cultural_parameter = X }
        culture = { has_cultural_pillar    = X }
    NOT-blocks (e.g. strength_in_numbers_heavy_maa_ban) and landless-adventurer
    alternatives (which use `location.culture` instead of `culture`) are
    discarded so we only keep the primary recruitment requirement.
  - Skip the MAA if no cultural trigger can be extracted (these use bespoke
    triggers like `ithilien_rangers_trigger = yes` and don't belong in a
    random recruitment list).

A `scope:actor = { is_elf = yes }` predicate is appended for every MAA defined
in lotr_elven_regiment_types.txt, matching the convention already in the file.

The script then rewrites two regions of effects_to_change.txt in place:
  1. The LotR portion of `ep3_pick_random_maa_regiment_effect`'s random_list
     (between the `### LotR ###` header and the `### ORCS ###` /
     `### Vanilla ###` markers - the vanilla / accolade / fallback content
     after that point is preserved verbatim).
  2. The entire switch body of `ep3_create_random_maa_regiment_effect`, which
     only ever contained LotR cases.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
EFFECTS_FILE = SCRIPT_DIR / "effects_to_change.txt"
REGIMENT_GLOB = "lotr_*_regiment_types.txt"
ELVEN_FILENAME = "lotr_elven_regiment_types.txt"

# These cultural parameters appear inside NOT-blocks and are exclusions, not
# requirements. They should not surface as triggers in the random_list.
EXCLUSION_PARAMS = {"strength_in_numbers_heavy_maa_ban"}

CULTURE_PRED_RE = re.compile(
    r"(?<![A-Za-z_.])culture\s*\??=\s*\{\s*"
    r"has_(innovation|cultural_tradition|cultural_parameter|cultural_pillar)"
    r"\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}"
)


# --------------------------------------------------------------------------- #
# Lightweight CK3 syntax helpers
# --------------------------------------------------------------------------- #

def strip_comments(text: str) -> str:
    """Drop `#` line-comments while preserving line breaks."""
    out = []
    for line in text.splitlines(keepends=True):
        # Preserve trailing newline; cut off comment from the rest.
        nl = "\n" if line.endswith("\n") else ""
        body = line[:-1] if nl else line
        idx = body.find("#")
        if idx >= 0:
            body = body[:idx]
        out.append(body + nl)
    return "".join(out)


def find_matching_brace(text: str, open_idx: int) -> int:
    """Given the index of '{', return the index just past the matching '}'."""
    if text[open_idx] != "{":
        raise ValueError(f"expected '{{' at index {open_idx}, got {text[open_idx]!r}")
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced braces")


def iter_top_level_blocks(text: str) -> Iterator[tuple[str, str]]:
    """Yield (name, inner_body) for every depth-0 `name = { ... }` block."""
    text = strip_comments(text)
    i = 0
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
            i += 1
            continue
        if c == "}":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{", text[i:])
            if m:
                name = m.group(1)
                brace_idx = i + m.end() - 1
                end = find_matching_brace(text, brace_idx)
                yield name, text[brace_idx + 1 : end - 1]
                i = end
                continue
        i += 1


def find_can_recruit_body(block_body: str) -> str | None:
    m = re.search(r"\bcan_recruit\s*=\s*\{", block_body)
    if not m:
        return None
    brace_idx = m.end() - 1
    end = find_matching_brace(block_body, brace_idx)
    return block_body[brace_idx + 1 : end - 1]


def remove_not_blocks(body: str) -> str:
    """Strip every `NOT = { ... }` block (with its content)."""
    out = []
    i = 0
    while i < len(body):
        m = re.match(r"NOT\s*=\s*\{", body[i:])
        if m:
            brace_idx = i + m.end() - 1
            end = find_matching_brace(body, brace_idx)
            i = end
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------- #
# MAA extraction
# --------------------------------------------------------------------------- #

def is_always_no(can_recruit_body: str) -> bool:
    return re.search(r"\balways\s*=\s*no\b", remove_not_blocks(can_recruit_body)) is not None


def extract_triggers(can_recruit_body: str) -> list[tuple[str, str]]:
    """Distinct (predicate_name, value) pairs found outside any NOT-block."""
    body = remove_not_blocks(can_recruit_body)
    seen: list[tuple[str, str]] = []
    for m in CULTURE_PRED_RE.finditer(body):
        kind = "has_" + m.group(1)
        value = m.group(2)
        if value in EXCLUSION_PARAMS:
            continue
        pair = (kind, value)
        if pair not in seen:
            seen.append(pair)
    return seen


def looks_like_maa(block_body: str) -> bool:
    """Heuristic to filter out helper/non-MAA top-level blocks."""
    return ("can_recruit" in block_body) or re.search(r"\btype\s*=\s*[a-z_]+", block_body) is not None


def parse_regiment_file(path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    text = path.read_text(encoding="utf-8")
    out = []
    for name, body in iter_top_level_blocks(text):
        if not looks_like_maa(body):
            continue
        cr = find_can_recruit_body(body)
        if cr is None:
            continue
        if is_always_no(cr):
            continue
        triggers = extract_triggers(cr)
        if not triggers:
            continue
        out.append((name, triggers))
    return out


# --------------------------------------------------------------------------- #
# Effect-snippet rendering
# --------------------------------------------------------------------------- #

ENTRY_INDENT = "\t\t\t\t"           # inside random_list { ... }
SWITCH_INDENT = "\t\t\t"            # inside switch { ... }


def render_trigger(triggers: list[tuple[str, str]], is_elf: bool) -> str:
    lines: list[str] = []
    if len(triggers) == 1:
        kind, value = triggers[0]
        lines.append(f"{ENTRY_INDENT}\t\tculture = {{ {kind} = {value} }}")
    else:
        lines.append(f"{ENTRY_INDENT}\t\tOR = {{")
        for kind, value in triggers:
            lines.append(f"{ENTRY_INDENT}\t\t\tculture = {{ {kind} = {value} }}")
        lines.append(f"{ENTRY_INDENT}\t\t}}")
    if is_elf:
        lines.append(f"{ENTRY_INDENT}\t\tscope:actor = {{ is_elf = yes }}")
    return "\n".join(lines)


def render_pick_entry(name: str, triggers: list[tuple[str, str]], is_elf: bool) -> str:
    return (
        f"{ENTRY_INDENT}1 = {{\n"
        f"{ENTRY_INDENT}\ttrigger = {{\n"
        f"{render_trigger(triggers, is_elf)}\n"
        f"{ENTRY_INDENT}\t}}\n"
        f"{ENTRY_INDENT}\tsave_scope_value_as = {{\n"
        f"{ENTRY_INDENT}\t\tname = maa_to_create\n"
        f"{ENTRY_INDENT}\t\tvalue = flag:{name}\n"
        f"{ENTRY_INDENT}\t}}\n"
        f"{ENTRY_INDENT}}}"
    )


def render_switch_entry(name: str) -> str:
    return (
        f"{SWITCH_INDENT}flag:{name} = {{\n"
        f"{SWITCH_INDENT}\tcreate_maa_or_upgrade_regiment_effect = {{\n"
        f"{SWITCH_INDENT}\t\tTYPE = {name}\n"
        f"{SWITCH_INDENT}\t\tSIZE = $SIZE$\n"
        f"{SWITCH_INDENT}\t}}\n"
        f"{SWITCH_INDENT}}}"
    )


# --------------------------------------------------------------------------- #
# File rewriting
# --------------------------------------------------------------------------- #

def rewrite_pick_effect(text: str, generated_block: str) -> str:
    """Replace the LotR slice of ep3_pick_random_maa_regiment_effect's random_list."""
    header = "### LotR ###\n"
    header_idx = text.find(header)
    if header_idx == -1:
        raise SystemExit("Could not find `### LotR ###` header in pick effect.")
    # The decorative `############\n` line directly after the header marks the
    # real start of the LotR entries.
    after_dashes = text.find("############\n", header_idx + len(header))
    if after_dashes == -1:
        raise SystemExit("Could not locate closing `############` of LotR header.")
    content_start = after_dashes + len("############\n")

    # The LotR block ends right before the `### ORCS ###` separator.
    end_marker = text.find("### ORCS ###", content_start)
    if end_marker == -1:
        raise SystemExit("Could not find `### ORCS ###` marker.")
    line_start = text.rfind("\n", 0, end_marker) + 1

    return text[:content_start] + generated_block + "\n" + text[line_start:]


def rewrite_create_effect(text: str, generated_block: str) -> str:
    """Replace the entire switch body of ep3_create_random_maa_regiment_effect."""
    anchor = text.find("ep3_create_random_maa_regiment_effect")
    if anchor == -1:
        raise SystemExit("Could not find ep3_create_random_maa_regiment_effect.")
    sw = text.find("switch = {", anchor)
    if sw == -1:
        raise SystemExit("Could not find switch in create effect.")
    brace_idx = text.find("{", sw)
    brace_end = find_matching_brace(text, brace_idx)

    new_body = (
        "{\n"
        f"{SWITCH_INDENT}trigger = scope:maa_to_create\n"
        f"{generated_block}\n"
        "\t\t}"
    )
    return text[:brace_idx] + new_body + text[brace_end:]


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main() -> int:
    regiment_files = sorted(SCRIPT_DIR.glob(REGIMENT_GLOB))
    if not regiment_files:
        print(f"No regiment files matching {REGIMENT_GLOB} found in {SCRIPT_DIR}.",
              file=sys.stderr)
        return 1

    all_maa: dict[str, tuple[list[tuple[str, str]], bool, str]] = {}
    skipped: list[tuple[str, str]] = []

    for path in regiment_files:
        is_elf = (path.name == ELVEN_FILENAME)
        text = path.read_text(encoding="utf-8")

        for name, body in iter_top_level_blocks(text):
            if not looks_like_maa(body):
                continue
            cr = find_can_recruit_body(body)
            if cr is None:
                skipped.append((name, "no can_recruit block"))
                continue
            if is_always_no(cr):
                skipped.append((name, "can_recruit = always no"))
                continue
            triggers = extract_triggers(cr)
            if not triggers:
                skipped.append((name, "no cultural trigger"))
                continue
            if name in all_maa:
                continue
            all_maa[name] = (triggers, is_elf, path.name)

    if not all_maa:
        print("No MAA types parsed; aborting.", file=sys.stderr)
        return 1

    # Stable, source-grouped ordering: by source file, then alphabetical.
    ordered = sorted(all_maa.items(), key=lambda kv: (kv[1][2], kv[0]))

    pick_entries: list[str] = []
    switch_entries: list[str] = []
    current_source: str | None = None
    for name, (triggers, is_elf, source) in ordered:
        if source != current_source:
            tag = source.replace("lotr_", "").replace("_regiment_types.txt", "")
            pick_entries.append(f"{ENTRY_INDENT}### {tag} ###")
            switch_entries.append(f"{SWITCH_INDENT}### {tag} ###")
            current_source = source
        pick_entries.append(render_pick_entry(name, triggers, is_elf))
        switch_entries.append(render_switch_entry(name))

    pick_block = "\n".join(pick_entries)
    switch_block = "\n".join(switch_entries)

    text = EFFECTS_FILE.read_text(encoding="utf-8")
    text = rewrite_pick_effect(text, pick_block)
    text = rewrite_create_effect(text, switch_block)
    EFFECTS_FILE.write_text(text, encoding="utf-8")

    print(f"Wrote {len(all_maa)} MAA entries to {EFFECTS_FILE.name}.")
    if skipped:
        print(f"Skipped {len(skipped)} block(s):")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Line-level diffs between resume versions, for the console and the report."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

# Row kinds. ``skip`` stands for a run of unchanged lines that was collapsed.
EQUAL = "equal"
ADD = "add"
REMOVE = "remove"
SKIP = "skip"


@dataclass(frozen=True)
class DiffRow:
    """One row of a diff: a line, and what happened to it."""

    kind: str
    text: str
    old: int | None = None
    new: int | None = None
    count: int = 1  # for ``skip`` rows: how many unchanged lines are hidden here

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "old": self.old,
            "new": self.new,
            "count": self.count,
        }


@dataclass(frozen=True)
class Diff:
    """A readable diff plus the counts the views show next to it."""

    rows: tuple[DiffRow, ...]
    added: int
    removed: int
    unchanged: int

    @property
    def changed(self) -> bool:
        return self.added > 0 or self.removed > 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "rows": [row.to_payload() for row in self.rows],
            "added": self.added,
            "removed": self.removed,
            "unchanged": self.unchanged,
        }


def line_diff(before: str, after: str, context: int = 2) -> Diff:
    """Diff two versions of a resume, collapsing long stretches of equal lines.

    ``context`` unchanged lines are kept on each side of a change, so the reader can see
    where a change sits; anything further away becomes one ``skip`` row.
    """
    old_lines = before.splitlines()
    new_lines = after.splitlines()
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    rows: list[DiffRow] = []
    added = removed = unchanged = skipped = 0
    old_no = new_no = 1

    def flush_skip() -> None:
        nonlocal skipped
        if skipped:
            rows.append(DiffRow(kind=SKIP, text=f"{skipped} unchanged lines", count=skipped))
            skipped = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            run = i2 - i1
            for offset in range(run):
                if offset < context or offset >= run - context:
                    flush_skip()
                    rows.append(
                        DiffRow(kind=EQUAL, text=old_lines[i1 + offset], old=old_no, new=new_no)
                    )
                else:
                    skipped += 1
                unchanged += 1
                old_no += 1
                new_no += 1
            continue

        flush_skip()
        for index in range(i1, i2):
            rows.append(DiffRow(kind=REMOVE, text=old_lines[index], old=old_no))
            removed += 1
            old_no += 1
        for index in range(j1, j2):
            rows.append(DiffRow(kind=ADD, text=new_lines[index], new=new_no))
            added += 1
            new_no += 1

    flush_skip()
    return Diff(rows=tuple(rows), added=added, removed=removed, unchanged=unchanged)

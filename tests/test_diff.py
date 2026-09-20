"""Tests for polisher.diff."""

from polisher.diff import ADD, SKIP, DiffRow, line_diff


def test_identical_texts_produce_no_changes() -> None:
    d = line_diff("a\nb\nc", "a\nb\nc")
    assert d.added == 0
    assert d.removed == 0
    assert d.unchanged == 3


def test_single_line_addition() -> None:
    d = line_diff("a\nb", "a\nb\nc")
    assert d.added == 1
    assert d.removed == 0
    assert any(row.kind == ADD and row.text == "c" for row in d.rows)


def test_single_line_removal() -> None:
    d = line_diff("a\nb\nc", "a\nc")
    assert d.removed == 1
    assert d.added == 0


def test_empty_before() -> None:
    d = line_diff("", "hello")
    assert d.added == 1
    assert d.removed == 0


def test_empty_after() -> None:
    d = line_diff("hello", "")
    assert d.removed == 1
    assert d.added == 0


def test_skip_row_collapses_long_equal_runs() -> None:
    long = "\n".join(f"line {i}" for i in range(20))
    changed = long + "\nnew line"
    d = line_diff(long, changed)
    assert any(row.kind == SKIP for row in d.rows)


def test_changed_property() -> None:
    assert line_diff("a", "b").changed
    assert not line_diff("a", "a").changed


def test_to_payload_round_trips() -> None:
    d = line_diff("x\ny", "x\nz")
    payload = d.to_payload()
    assert "rows" in payload
    assert payload["added"] == 1
    assert payload["removed"] == 1


def test_diff_row_payload() -> None:
    row = DiffRow(kind=ADD, text="hello", new=1)
    p = row.to_payload()
    assert p["kind"] == ADD
    assert p["text"] == "hello"
    assert p["new"] == 1
    assert p["old"] is None

"""First-class rulebook data: strict parsing, validation, and precedence.

Rules start as TOML so they can be inspected, hashed, diffed, and surfaced in the page.
This module keeps the schema explicit and rejects anything ambiguous.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import tomllib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

RuleKind = Literal["must", "must_not", "prefer", "format"]
RuleSource = Literal["builtin", "user", "job"]
RuleCheck = Literal["code", "jev"]
RuleSeverity = Literal["blocking", "advisory"]
CodeCheckName = Literal[
    "page_budget",
    "banned_phrases",
    "first_person",
    "us_spelling",
    "required_strings",
    "sections",
    "emoji",
    "markdown",
]
RuleState = Literal["passed", "violated", "not_checkable"]

VALID_KINDS = frozenset(("must", "must_not", "prefer", "format"))
VALID_SOURCES = frozenset(("builtin", "user", "job"))
VALID_CHECKS = frozenset(("code", "jev"))
VALID_SEVERITIES = frozenset(("blocking", "advisory"))
PRECEDENCE_ORDER = ("grounding", "user", "job", "builtin")

_SOURCE_PRIORITY = {"user": 0, "job": 1, "builtin": 2}
_KIND_PRIORITY = {"must_not": 0, "must": 1, "format": 2, "prefer": 3}
_SEVERITY_PRIORITY = {"blocking": 0, "advisory": 1}
_FIELDS = ("id", "kind", "text", "source", "check", "severity")
_WORD_RE = re.compile(r"\b[\w-]+\b")
_SECTION_RE = re.compile(r"^[A-Z][A-Z /&-]{1,40}$")
_DATE_MON_RE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{4}\b")
_DATE_MONTH_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b"
)
_DATE_YEAR_RE = re.compile(r"\b\d{4}\b")
_BULLET_PREFIXES = ("-", "•", "*", "–", "—", "·")
_MARKDOWN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("code fence", re.compile(r"```")),
    ("heading", re.compile(r"(?m)^#{1,6}\s+\S")),
    ("table", re.compile(r"(?m)^\|.+\|\s*$")),
    ("table divider", re.compile(r"(?m)^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")),
    ("link", re.compile(r"\[[^\]]+\]\([^)]+\)")),
    ("emphasis", re.compile(r"(\*\*|__)[^*_]+(\*\*|__)")),
)
_UK_TO_US = {
    "analyse": "analyze",
    "analysed": "analyzed",
    "behaviour": "behavior",
    "colour": "color",
    "favour": "favor",
    "labour": "labor",
    "organisation": "organization",
    "organise": "organize",
    "organised": "organized",
    "organising": "organizing",
    "optimise": "optimize",
    "optimised": "optimized",
    "optimisation": "optimization",
    "programme": "program",
}
_CODE_CHECKS: dict[str, Callable[..., CodeCheckResult]]


@dataclass(frozen=True)
class CodeCheckResult:
    """One deterministic rule evaluation."""

    name: str
    passed: bool
    message: str
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeCheckSpec:
    """A configured deterministic check ready to run against resume text."""

    name: CodeCheckName
    params: dict[str, Any] = field(default_factory=dict)

    def run(self, text: str) -> CodeCheckResult:
        return run_code_check(self.name, text, **self.params)


@dataclass(frozen=True)
class RuleResult:
    """One rule evaluated against one draft."""

    rule_id: str
    state: RuleState
    findings: tuple[str, ...] = ()
    checks: tuple[CodeCheckResult, ...] = ()
    probability: float | None = None


class RuleValidationError(ValueError):
    """Raised when a rules file is structurally valid TOML but invalid rule data."""


@dataclass(frozen=True)
class Rule:
    """One resume rule, explicit enough to show, hash, and enforce."""

    id: str
    kind: RuleKind
    text: str
    source: RuleSource
    check: RuleCheck
    severity: RuleSeverity

    def __post_init__(self) -> None:
        _require_non_empty("id", self.id)
        _require_choice("kind", self.kind, VALID_KINDS)
        _require_non_empty("text", self.text)
        _require_choice("source", self.source, VALID_SOURCES)
        _require_choice("check", self.check, VALID_CHECKS)
        _require_choice("severity", self.severity, VALID_SEVERITIES)

    @property
    def precedence(self) -> tuple[int, int, int, str]:
        return precedence_key(self)

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "source": self.source,
            "check": self.check,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class RuleBook:
    """A validated, ordered set of rules."""

    rules: tuple[Rule, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        duplicates: list[str] = []
        for rule in self.rules:
            if rule.id in seen and rule.id not in duplicates:
                duplicates.append(rule.id)
            seen.add(rule.id)
        if duplicates:
            raise RuleValidationError(f"rules.id: duplicate id(s): {', '.join(duplicates)}")

    def __iter__(self):
        return iter(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    def ordered(self) -> tuple[Rule, ...]:
        return tuple(sorted(self.rules, key=precedence_key))

    def sources(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(rule.source for rule in self.ordered()))

    def to_list(self) -> list[dict[str, str]]:
        return [rule.to_dict() for rule in self.rules]

    def to_toml(self) -> str:
        return dump_rules_toml(self)

    def short_hash(self) -> str:
        digest = hashlib.sha256(self.to_toml().encode()).hexdigest()
        return digest[:16]


def compose_rulebooks(*rulebooks: RuleBook | None) -> RuleBook:
    """Merge multiple rulebooks into one active rulebook.

    Built-in guidance and customer rules should both apply to a run. Duplicate ids still fail:
    a reader has to be able to tell which rule actually fired.
    """

    merged: list[Rule] = []
    for rulebook in rulebooks:
        if rulebook is None:
            continue
        merged.extend(rulebook.rules)
    return RuleBook(rules=tuple(merged))


def precedence_key(rule: Rule) -> tuple[int, int, int, str]:
    """Sort higher-precedence rules first, with stable ties by id."""

    return (
        _SOURCE_PRIORITY[rule.source],
        _KIND_PRIORITY[rule.kind],
        _SEVERITY_PRIORITY[rule.severity],
        rule.id,
    )


def parse_rules_toml(text: str) -> RuleBook:
    """Parse a TOML rules file from text and return a validated rulebook."""

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuleValidationError(f"toml: {exc}") from exc
    return parse_rules_data(data)


def parse_rules_data(data: dict[str, Any]) -> RuleBook:
    """Validate already-parsed TOML data."""

    entries = data.get("rules")
    if entries is None:
        raise RuleValidationError("rules: missing [[rules]] entries")
    if not isinstance(entries, list):
        raise RuleValidationError("rules: expected a list of tables")
    rules = tuple(_parse_rule(index, entry) for index, entry in enumerate(entries))
    return RuleBook(rules=rules)


def load_rules(path: Path) -> RuleBook:
    """Read and validate a TOML rulebook, exiting with a readable field error."""

    try:
        text = path.read_text()
    except FileNotFoundError:
        raise SystemExit(f"{path} not found")
    try:
        return parse_rules_toml(text)
    except RuleValidationError as exc:
        raise SystemExit(f"{path}: {exc}") from exc


def dump_rules_toml(rulebook: RuleBook | tuple[Rule, ...] | list[Rule]) -> str:
    """Render a canonical TOML form so a valid rulebook round-trips exactly."""

    rules = rulebook.rules if isinstance(rulebook, RuleBook) else tuple(rulebook)
    blocks: list[str] = []
    for rule in rules:
        blocks.append("[[rules]]")
        for field_name in _FIELDS:
            blocks.append(f"{field_name} = {json.dumps(getattr(rule, field_name))}")
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def available_code_checks() -> tuple[str, ...]:
    return tuple(sorted(_CODE_CHECKS))


def run_code_check(name: CodeCheckName | str, text: str, **kwargs: Any) -> CodeCheckResult:
    """Run one registered deterministic check."""

    try:
        check = _CODE_CHECKS[name]
    except KeyError as exc:
        choices = ", ".join(available_code_checks())
        raise RuleValidationError(f"code_check: expected one of {choices}; got {name!r}") from exc
    return check(text, **kwargs)


def detect_sections(text: str) -> tuple[str, ...]:
    """Extract likely resume section headings in canonical lowercase form."""

    sections: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 42:
            continue
        if line.startswith(("-", "*", "•")) or any(char.isdigit() for char in line):
            continue
        if _SECTION_RE.fullmatch(line):
            normalized = " ".join(line.lower().split())
            if normalized not in sections:
                sections.append(normalized)
    return tuple(sections)


def format_ledger(text: str) -> dict[str, Any]:
    """Summarize the resume's shape and common formatting risks."""

    raw_lines = [line.rstrip() for line in text.splitlines()]
    non_empty = [line.strip() for line in raw_lines if line.strip()]
    bullets = [
        line.strip().lstrip("".join(_BULLET_PREFIXES)).strip()
        for line in raw_lines
        if line.strip().startswith(_BULLET_PREFIXES)
    ]
    bullet_word_counts = [len(_WORD_RE.findall(line)) for line in bullets]
    overlong = [
        line
        for line, count in zip(bullets, bullet_word_counts, strict=True)
        if count > 28
    ]
    duplicate_claims = _duplicate_claims(bullets)
    near_duplicates = _near_duplicate_claims(bullets)
    sections = list(detect_sections(text))
    date_styles = _date_styles(non_empty)
    return {
        "lines": len(non_empty),
        "words": len(_WORD_RE.findall(text)),
        "sections": sections,
        "role_bullets": _role_bullet_counts(raw_lines),
        "bullet_word_counts": bullet_word_counts,
        "overlong_bullets": overlong,
        "date_styles": date_styles,
        "date_consistent": len(date_styles) <= 1,
        "duplicate_claims": duplicate_claims,
        "near_duplicate_claims": near_duplicates,
    }


def evaluate_rule(
    rule: Rule,
    text: str,
    *,
    code_checks: tuple[CodeCheckSpec, ...] = (),
) -> RuleResult:
    """Evaluate one rule against a draft, or mark it not checkable."""

    if rule.check != "code" or not code_checks:
        return RuleResult(rule_id=rule.id, state="not_checkable")
    results = tuple(spec.run(text) for spec in code_checks)
    findings = tuple(
        dict.fromkeys(finding for result in results for finding in result.findings)
    )
    state: RuleState = "passed" if all(result.passed for result in results) else "violated"
    return RuleResult(rule_id=rule.id, state=state, findings=findings, checks=results)


def evaluate_rulebook(
    rulebook: RuleBook,
    text: str,
    *,
    code_checks: dict[str, tuple[CodeCheckSpec, ...]] | None = None,
) -> tuple[RuleResult, ...]:
    """Evaluate each rule in order, using any configured deterministic checks."""

    configured_checks = code_checks or {}
    return tuple(
        evaluate_rule(rule, text, code_checks=configured_checks.get(rule.id, ()))
        for rule in rulebook.ordered()
    )


def _parse_rule(index: int, entry: Any) -> Rule:
    location = f"rules[{index}]"
    if not isinstance(entry, dict):
        raise RuleValidationError(f"{location}: expected a table")

    unknown = sorted(set(entry) - set(_FIELDS))
    if unknown:
        raise RuleValidationError(f"{location}.{unknown[0]}: unknown field")

    values: dict[str, str] = {}
    for field_name in _FIELDS:
        if field_name not in entry:
            raise RuleValidationError(f"{location}.{field_name}: missing field")
        value = entry[field_name]
        if not isinstance(value, str):
            raise RuleValidationError(f"{location}.{field_name}: expected a string")
        values[field_name] = value.strip()

    try:
        return Rule(
            id=values["id"],
            kind=values["kind"],
            text=values["text"],
            source=values["source"],
            check=values["check"],
            severity=values["severity"],
        )
    except RuleValidationError as exc:
        raise RuleValidationError(f"{location}.{exc}") from exc


def _require_non_empty(field: str, value: str) -> None:
    if not value.strip():
        raise RuleValidationError(f"{field}: expected a non-empty string")


def _require_choice(field: str, value: str, valid: frozenset[str]) -> None:
    if value not in valid:
        choices = ", ".join(sorted(valid))
        raise RuleValidationError(f"{field}: expected one of {choices}; got {value!r}")


def _check_page_budget(
    text: str, *, max_words: int = 900, max_lines: int = 80
) -> CodeCheckResult:
    words = len(_WORD_RE.findall(text))
    lines = sum(1 for line in text.splitlines() if line.strip())
    findings: list[str] = []
    if words > max_words:
        findings.append(f"{words} words exceeds {max_words}")
    if lines > max_lines:
        findings.append(f"{lines} non-empty lines exceeds {max_lines}")
    if findings:
        return CodeCheckResult(
            name="page_budget",
            passed=False,
            message="resume exceeds the configured page budget",
            findings=tuple(findings),
        )
    return CodeCheckResult(
        name="page_budget",
        passed=True,
        message="resume stays within the configured page budget",
    )


def _check_banned_phrases(
    text: str, *, phrases: tuple[str, ...] = ("responsible for", "helped with", "passionate")
) -> CodeCheckResult:
    lowered = text.lower()
    found = tuple(phrase for phrase in phrases if phrase.lower() in lowered)
    if found:
        return CodeCheckResult(
            name="banned_phrases",
            passed=False,
            message="resume uses banned phrases",
            findings=found,
        )
    return CodeCheckResult(
        name="banned_phrases",
        passed=True,
        message="resume avoids the banned phrases",
    )


def _check_first_person(text: str) -> CodeCheckResult:
    matches = tuple(
        dict.fromkeys(
            match.group(0).lower()
            for match in re.finditer(
                r"\b(i|i'm|i’ve|i've|i’d|i'd|i’ll|i'll|me|my|mine|myself)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
    )
    if matches:
        return CodeCheckResult(
            name="first_person",
            passed=False,
            message="resume uses first-person pronouns",
            findings=matches,
        )
    return CodeCheckResult(
        name="first_person",
        passed=True,
        message="resume avoids first-person pronouns",
    )


def _check_us_spelling(text: str) -> CodeCheckResult:
    words = [word.lower() for word in re.findall(r"\b[A-Za-z]+\b", text)]
    findings = tuple(
        dict.fromkeys(f"{word} -> {_UK_TO_US[word]}" for word in words if word in _UK_TO_US)
    )
    if findings:
        return CodeCheckResult(
            name="us_spelling",
            passed=False,
            message="resume uses UK spellings where US spellings are expected",
            findings=findings,
        )
    return CodeCheckResult(
        name="us_spelling",
        passed=True,
        message="resume uses US spellings",
    )


def _check_required_strings(
    text: str, *, strings: tuple[str, ...], case_sensitive: bool = False
) -> CodeCheckResult:
    haystack = text if case_sensitive else text.lower()
    missing = tuple(
        value
        for value in strings
        if (value if case_sensitive else value.lower()) not in haystack
    )
    if missing:
        return CodeCheckResult(
            name="required_strings",
            passed=False,
            message="resume is missing required strings",
            findings=missing,
        )
    return CodeCheckResult(
        name="required_strings",
        passed=True,
        message="resume includes all required strings",
    )


def _check_sections(
    text: str,
    *,
    required_sections: tuple[str, ...] = (),
    forbidden_sections: tuple[str, ...] = (),
) -> CodeCheckResult:
    sections = set(detect_sections(text))
    missing = tuple(
        section for section in required_sections if _normalize_section_name(section) not in sections
    )
    forbidden = tuple(
        section for section in forbidden_sections if _normalize_section_name(section) in sections
    )
    findings = tuple(f"missing: {section}" for section in missing) + tuple(
        f"forbidden: {section}" for section in forbidden
    )
    if findings:
        return CodeCheckResult(
            name="sections",
            passed=False,
            message="resume section rules failed",
            findings=findings,
        )
    return CodeCheckResult(
        name="sections",
        passed=True,
        message="resume section rules passed",
        findings=tuple(sorted(sections)),
    )


def _check_emoji(text: str) -> CodeCheckResult:
    findings = tuple(dict.fromkeys(char for char in text if _is_emoji(char)))
    if findings:
        return CodeCheckResult(
            name="emoji",
            passed=False,
            message="resume contains emoji",
            findings=findings,
        )
    return CodeCheckResult(
        name="emoji",
        passed=True,
        message="resume contains no emoji",
    )


def _check_markdown(text: str) -> CodeCheckResult:
    findings: list[str] = []
    for label, pattern in _MARKDOWN_PATTERNS:
        if pattern.search(text):
            findings.append(label)
    if findings:
        return CodeCheckResult(
            name="markdown",
            passed=False,
            message="resume contains markdown syntax",
            findings=tuple(dict.fromkeys(findings)),
        )
    return CodeCheckResult(
        name="markdown",
        passed=True,
        message="resume contains no markdown syntax",
    )


def _normalize_section_name(name: str) -> str:
    return " ".join(name.lower().split())


def _date_styles(lines: list[str]) -> list[str]:
    styles: list[str] = []
    for line in lines:
        if _DATE_MON_RE.search(line):
            styles.append("mon_year")
        elif _DATE_MONTH_RE.search(line):
            styles.append("month_year")
        elif _DATE_YEAR_RE.search(line):
            styles.append("year_only")
    return list(dict.fromkeys(styles))


def _role_bullet_counts(lines: list[str]) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    in_experience = False
    current_role: str | None = None
    bullet_count = 0
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        section = _normalize_section_name(line) if _SECTION_RE.fullmatch(line) else None
        if section == "experience":
            in_experience = True
            current_role = None
            bullet_count = 0
            continue
        if section and in_experience and section != "experience":
            break
        if not in_experience:
            continue
        if line.startswith(_BULLET_PREFIXES):
            if current_role is None:
                current_role = "(unlabelled role)"
            bullet_count += 1
            continue
        if _line_looks_like_date(line):
            continue
        if current_role is not None and bullet_count:
            roles.append({"role": current_role, "bullets": bullet_count})
            bullet_count = 0
        current_role = line
    if current_role is not None and bullet_count:
        roles.append({"role": current_role, "bullets": bullet_count})
    return roles


def _line_looks_like_date(line: str) -> bool:
    if _DATE_MON_RE.search(line) or _DATE_MONTH_RE.search(line):
        return True
    years = _DATE_YEAR_RE.findall(line)
    return len(years) >= 2 or (len(years) == 1 and "present" in line.lower())


def _duplicate_claims(bullets: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for bullet in bullets:
        normalized = _normalize_claim(bullet)
        if not normalized:
            continue
        if normalized in seen:
            duplicates.append(bullet)
        else:
            seen[normalized] = bullet
    return duplicates


def _near_duplicate_claims(bullets: list[str]) -> list[str]:
    findings: list[str] = []
    for left, right in itertools.combinations(bullets, 2):
        left_words = set(_normalize_claim(left).split())
        right_words = set(_normalize_claim(right).split())
        if not left_words or not right_words:
            continue
        overlap = len(left_words & right_words) / len(left_words | right_words)
        if 0.72 <= overlap < 1.0:
            findings.append(f"{left} || {right}")
    return findings


def _normalize_claim(text: str) -> str:
    words = [word.lower() for word in _WORD_RE.findall(text) if len(word) >= 3]
    return " ".join(words)


def _is_emoji(char: str) -> bool:
    codepoint = ord(char)
    if 0x1F300 <= codepoint <= 0x1FAFF:
        return True
    if 0x2600 <= codepoint <= 0x27BF:
        return unicodedata.category(char) == "So"
    return False


_CODE_CHECKS = {
    "page_budget": _check_page_budget,
    "banned_phrases": _check_banned_phrases,
    "first_person": _check_first_person,
    "us_spelling": _check_us_spelling,
    "required_strings": _check_required_strings,
    "sections": _check_sections,
    "emoji": _check_emoji,
    "markdown": _check_markdown,
}
"""Target profile: the facts you feed in about who/what the wordlist is for.

The whole premise of wd_gen is "give the most info you can" — the more the
profile knows about the owner, the framework, the purpose and the surrounding
trivia, the more pointed (and more unhinged) the output gets. This module is
the structured container for that info plus its loaders.

A profile can be built three ways, in increasing convenience:
  * programmatically via ``Profile(...)`` / ``Profile.from_mapping(...)``
  * from a file (JSON, or a dead-simple ``field: a, b, c`` text format)
  * from CLI flags, merged on top of any file (see cli.py)

No third-party YAML dep on purpose — the tool ships with ``dependencies = []``.
The simple text format covers the same ergonomics for the 90% case.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path

# Recognised profile fields. Order here is the order tokens are emitted in,
# which (weakly) biases the generator toward the more identifying material.
_FIELDS = (
    "names",
    "org",
    "framework",
    "purpose",
    "keywords",
    "pets",
    "dates",
    "extras",
)

# Field-name aliases accepted in files/flags so you don't have to remember the
# canonical spelling. Maps alias -> canonical field.
_ALIASES = {
    "name": "names",
    "owner": "names",
    "owners": "names",
    "person": "names",
    "people": "names",
    "company": "org",
    "organization": "org",
    "organisation": "org",
    "team": "org",
    "frameworks": "framework",
    "stack": "framework",
    "tech": "framework",
    "purposes": "purpose",
    "goal": "purpose",
    "keyword": "keywords",
    "tags": "keywords",
    "pet": "pets",
    "animal": "pets",
    "animals": "pets",
    "date": "dates",
    "year": "dates",
    "years": "dates",
    "extra": "extras",
    "misc": "extras",
    "notes": "extras",
}


class ProfileError(Exception):
    """Raised when a profile file cannot be parsed."""


@dataclass
class Profile:
    """Everything wd_gen knows about the target."""

    names: list[str] = field(default_factory=list)
    org: list[str] = field(default_factory=list)
    framework: list[str] = field(default_factory=list)
    purpose: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    pets: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)

    def tokens(self) -> list[str]:
        """Flatten every field into a deduped, order-preserving token list."""
        seen: set[str] = set()
        out: list[str] = []
        for name in _FIELDS:
            for raw in getattr(self, name):
                tok = raw.strip()
                key = tok.lower()
                if tok and key not in seen:
                    seen.add(key)
                    out.append(tok)
        return out

    def is_empty(self) -> bool:
        return not any(getattr(self, name) for name in _FIELDS)

    def merge(self, other: Profile) -> Profile:
        """Return a new profile with ``other``'s values appended to ours."""
        kwargs = {}
        for name in _FIELDS:
            kwargs[name] = list(getattr(self, name)) + list(getattr(other, name))
        return Profile(**kwargs)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Profile:
        """Build a profile from a dict; unknown keys fall into ``extras``."""
        canonical = {f.name for f in fields(cls)}
        kwargs: dict[str, list[str]] = {name: [] for name in _FIELDS}
        for raw_key, value in data.items():
            key = _ALIASES.get(raw_key.lower(), raw_key.lower())
            if key not in canonical:
                key = "extras"
            kwargs[key].extend(_coerce_list(value))
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str | Path) -> Profile:
        """Load from a file. JSON if it parses as JSON, else the simple format."""
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProfileError(f"cannot read profile {p}: {exc}") from exc
        stripped = text.lstrip()
        if stripped.startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ProfileError(f"invalid JSON in {p}: {exc}") from exc
            if not isinstance(data, Mapping):
                raise ProfileError(f"{p}: top-level JSON must be an object")
            return cls.from_mapping(data)
        return cls.from_mapping(_parse_simple(text, p))


def _coerce_list(value: object) -> list[str]:
    """Turn a scalar, comma-string, or iterable into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, Iterable):
        out: list[str] = []
        for item in value:
            out.extend(_coerce_list(item))
        return out
    return [str(value)]


def _parse_simple(text: str, path: Path) -> dict[str, list[str]]:
    """Parse the ``field: a, b, c`` line format. ``#`` starts a comment."""
    data: dict[str, list[str]] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ProfileError(f"{path}:{lineno}: expected 'field: values', got {stripped!r}")
        key, _, rest = stripped.partition(":")
        data.setdefault(key.strip(), []).extend(_coerce_list(rest))
    return data

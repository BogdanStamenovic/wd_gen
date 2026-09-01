"""Realistic OSINT credential permutation — the CUPP + username-anarchy core.

Given a real person's name and facts, this produces the *plausible* usernames
and passwords that specific person would actually pick. Not random tumbling:
the shapes here are the ones people demonstrably choose — ``first+last``,
``f.last``, ``first`` + birth year, ``Name123!``, light leetspeak — enumerated
across the target's own tokens.

The two public generators, ``iter_usernames`` and ``iter_passwords``, yield
candidates; ``plausibility`` scores them so the ranked, capped output is
best-guess-first — which is exactly the order a CTF/OSINT attacker wants to try
them in. Everything is driven by the passed-in RNG, so ``--seed`` reproduces a
run; the value space is enumerated deterministically and only *sampled* where a
full cartesian product would explode.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterator, Sequence

from .profile import Profile

# Numeric suffixes people actually append, in rough order of how common they are.
COMMON_NUMBERS: tuple[str, ...] = (
    "1", "123", "12", "1234", "12345", "01", "007", "69", "007", "111",
    "000", "007", "21", "22", "23", "007", "420", "666", "777", "1337",
    "0", "2", "3", "7", "11", "99", "100", "007",
)

# Default birth-year-ish range appended to names (the classic "name+year").
DEFAULT_YEAR_RANGE = (1970, 2027)

# Symbols people put on the end (or occasionally the front) to satisfy a policy.
COMMON_SYMBOLS: tuple[str, ...] = ("!", "@", "#", "$", ".", "_", "*", "?", "1!", "!!", "123!")

# Leet swaps people actually use in handles/passwords — a conservative subset.
_REALISTIC_LEET = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7", "b": "8"}
_LEET_FULL = str.maketrans(_REALISTIC_LEET)

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


# --- token derivation -------------------------------------------------------


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _name_structures(profile: Profile) -> list[list[str]]:
    """Each names/extras entry split into its word parts, e.g. ['bogdan','stamenovix']."""
    out: list[list[str]] = []
    for entry in list(profile.names) + list(profile.extras):
        parts = _words(entry)
        if parts:
            out.append(parts)
    return out


def personal_tokens(profile: Profile) -> list[str]:
    """Flat, deduped, lowercased single-word tokens from every profile field."""
    seen: set[str] = set()
    out: list[str] = []
    for field in ("names", "org", "framework", "purpose", "keywords", "pets", "extras"):
        for entry in getattr(profile, field):
            for w in _words(entry):
                if w not in seen:
                    seen.add(w)
                    out.append(w)
    return out


def expand_dates(profile: Profile) -> list[str]:
    """Turn date-ish tokens into the numeric fragments people use in passwords.

    A full date yields YYYY, YY, DDMM, MMDD, DDMMYYYY, DD, MM; a bare year yields
    YYYY and YY. Deduped, order-preserving.
    """
    frags: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        if s and s not in seen:
            seen.add(s)
            frags.append(s)

    for entry in profile.dates:
        nums = re.findall(r"\d+", entry)
        joined = "".join(nums)
        year = next((n for n in nums if len(n) == 4), None)
        day = next((n for n in nums if len(n) <= 2 and 1 <= int(n) <= 31), None)
        month = next((n for n in nums if len(n) <= 2 and 1 <= int(n) <= 12), None)
        if year:
            add(year)
            add(year[2:])
        if day and month:
            dd, mm = day.zfill(2), month.zfill(2)
            add(dd + mm)
            add(mm + dd)
            if year:
                add(dd + mm + year)
                add(dd + mm + year[2:])
        add(day or "")
        add(month or "")
        # Fallback: whatever digits were there, as-is.
        add(joined)
    return frags


def _cap_variants(word: str) -> list[str]:
    """The capitalisations a person realistically types, most-common first."""
    out = [word, word.capitalize()]
    if word.upper() != word.capitalize():
        out.append(word.upper())
    return out


def _leet_variants(word: str) -> list[str]:
    """Plain, vowel-only leet, and full leet — deduped."""
    out = [word]
    vowels = {"a", "e", "i", "o"}
    partial = "".join(_REALISTIC_LEET.get(c, c) if c in vowels else c for c in word)
    full = word.translate(_LEET_FULL)
    for v in (partial, full):
        if v not in out and any(ch.isdigit() for ch in v):
            out.append(v)
    return out


def _number_bank(profile: Profile, year_range: tuple[int, int]) -> list[str]:
    """Date fragments (highest signal) + common numbers + a year range."""
    bank: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        if s and s not in seen:
            seen.add(s)
            bank.append(s)

    for frag in expand_dates(profile):
        add(frag)
    for n in COMMON_NUMBERS:
        add(n)
    lo, hi = year_range
    for y in range(lo, hi):
        add(str(y))
        add(str(y)[2:])
    return bank


# --- username permutations --------------------------------------------------


def _username_bases(profile: Profile) -> list[str]:
    """Handle base forms from name structure + standalone tokens (deduped)."""
    seen: set[str] = set()
    bases: list[str] = []

    def add(s: str) -> None:
        s = s.strip("._-")
        if s and s not in seen:
            seen.add(s)
            bases.append(s)

    for parts in _name_structures(profile):
        first = parts[0]
        add(first)
        if len(parts) >= 2:
            last = parts[-1]
            add(last)
            for sep in ("", ".", "_", "-"):
                add(first + sep + last)
                add(last + sep + first)
            add(first[0] + last)          # bstamenovix
            add(first + last[0])          # bogdans
            add(first[0] + "." + last)    # b.stamenovix
            add(first + "." + last[0])
            add(first[0] + last[0])       # bs (initials)
            # Truncations people actually use.
            for k in range(3, len(first)):
                add(first[:k])            # bog, bogd, ...
            add(first[0] + last[: max(3, len(last) // 2)])   # bstam / bstamen
            add(first[:3] + last[:3])     # bogsta
            add(first + last[:3])         # bogdansta
    for tok in personal_tokens(profile):
        add(tok)
    return bases


def iter_usernames(
    profile: Profile,
    *,
    year_range: tuple[int, int] = DEFAULT_YEAR_RANGE,
) -> Iterator[str]:
    """Yield plausible handle candidates for the target."""
    numbers = _number_bank(profile, year_range)
    for base in _username_bases(profile):
        for form in _leet_variants(base):
            yield form
            if len(form) > 2:
                yield form.capitalize()
            for num in numbers:
                yield form + num
            for num in numbers[:24]:
                yield form + "_" + num
                yield form + "." + num


# --- password permutations --------------------------------------------------


def _password_tokens(profile: Profile) -> list[str]:
    """Base word-tokens for passwords: personal tokens + glued name combos."""
    seen: set[str] = set()
    out: list[str] = []

    def add(s: str) -> None:
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    for tok in personal_tokens(profile):
        add(tok)
    for parts in _name_structures(profile):
        if len(parts) >= 2:
            add(parts[0] + parts[-1])       # bogdanstamenovix
            add(parts[0][0] + parts[-1])    # bstamenovix
            add(parts[0] + parts[-1][0])    # bogdans
    return out


def iter_passwords(
    profile: Profile,
    rng: random.Random,
    *,
    year_range: tuple[int, int] = DEFAULT_YEAR_RANGE,
) -> Iterator[str]:
    """Yield plausible password candidates for the target.

    ``rng`` is currently unused (the enumeration is fully deterministic) but is
    accepted so the signature matches the username generator and leaves room for
    future sampling without a call-site change.
    """
    del rng
    tokens = _password_tokens(profile)
    numbers = _number_bank(profile, year_range)
    sym_sample = COMMON_SYMBOLS

    for tok in tokens:
        for form in [*_cap_variants(tok), *_leet_variants(tok)]:
            yield form
            for num in numbers:
                yield form + num
            for sym in sym_sample:
                yield form + sym
            # The "policy-satisfying" shapes: word + number + symbol.
            for num in numbers[:16]:
                for sym in ("!", "@", "#", "$", "1!"):
                    yield form + num + sym
            for sym in ("!", "@"):
                for num in numbers[:8]:
                    yield sym + form + num

    # Two-token combos (name+pet, name+org, first+last already glued above too).
    for i, a in enumerate(tokens):
        for b in tokens:
            if a == b:
                continue
            combo = a + b
            yield combo
            yield combo.capitalize()
            for num in numbers[:20]:
                yield combo + num
                yield combo.capitalize() + num + "!"
        if i > 40:  # keep the O(n^2) bounded on large profiles
            break


# --- plausibility scoring ---------------------------------------------------

_YEAR_TAIL = re.compile(r"(19[6-9]\d|20[0-2]\d)$")
_COMMON_TAIL = re.compile(r"(123|1234|!|1!|69|007|321)$")


def plausibility(
    candidate: str,
    base_tokens: Sequence[str],
    hot_numbers: frozenset[str] = frozenset(),
) -> float:
    """How likely a real person picked this. Higher = try it earlier.

    ``hot_numbers`` are the target's OWN date fragments (birth year, DDMM, ...).
    A candidate ending in one of those outranks the same shape ending in a random
    year, and a plain name-handle with no digits at all stays near the top.
    """
    if not candidate:
        return -10.0
    low = candidate.lower()
    s = 0.0
    # Built from the target's own material — the whole premise.
    if any(tok and tok in low for tok in base_tokens):
        s += 3.0
    # The target's actual numbers (birthday etc.) are the strongest tail.
    if hot_numbers and any(candidate.endswith(h) for h in hot_numbers):
        s += 2.5
    elif _YEAR_TAIL.search(candidate):
        s += 0.4  # some year, but not one we know is meaningful to them
    if _COMMON_TAIL.search(candidate):
        s += 1.0
    # A plain word-handle (no digits, no symbols) is a top-tier guess too.
    if candidate.isalpha():
        s += 0.9
    # Capitalisation people actually use.
    if candidate[:1].isupper() and candidate[1:].islower():
        s += 0.8
    elif candidate.islower():
        s += 0.6
    # Length people actually pick (6–12 is the fat part of the distribution).
    n = len(candidate)
    if 6 <= n <= 12:
        s += 1.0
    elif n < 4:
        s -= 2.0
    elif n > 18:
        s -= 1.5
    # Leetspeak is real but rarer than plain — small nudge down so plain wins ties.
    if any(ch.isdigit() for ch in candidate) and re.search(r"[a-z][0-9][a-z]", low):
        s -= 0.4
    # Symbol soup is uncommon.
    symbols = sum(1 for c in candidate if not c.isalnum())
    if symbols > 2:
        s -= 1.0
    return s

"""The rule engine: classic password mangling, hashcat-flavoured.

Each rule is a pure function ``(word, rng) -> Iterable[str]`` registered by name
in ``RULES``. The generator picks a subset of rules (``--rules``) and applies
them to every seed word. Rules are applied *independently* per word rather than
as a full cartesian product — a full product of every rule against every word
blows up into millions of near-duplicates that all look the same and drown out
the interesting output. Bounded, varied breadth beats unbounded depth here.

Nothing in this module prints or holds global state; the RNG is passed in so the
whole pipeline stays reproducible under ``--seed``.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Iterator

# --- substitution + affix banks --------------------------------------------

# Each source char maps to the leet glyphs we're willing to swap in.
LEET_MAP: dict[str, tuple[str, ...]] = {
    "a": ("4", "@"),
    "b": ("8",),
    "e": ("3",),
    "g": ("9", "6"),
    "i": ("1", "!"),
    "l": ("1", "|"),
    "o": ("0",),
    "s": ("5", "$"),
    "t": ("7", "+"),
    "z": ("2",),
}

# Trailing punctuation runs. The eternal "must contain a special character".
SYMBOL_SUFFIXES: tuple[str, ...] = ("!", "!!", "!!!", "?", "@", "#", "$", "*", ".", "_", "!@#", "123!")

# Numeric suffixes people actually pick when a form yells "add a number".
NUMBER_SUFFIXES: tuple[str, ...] = (
    "1", "12", "123", "1234", "12345", "01", "007", "69", "420", "666",
    "1337", "9000", "2020", "2021", "2022", "2023", "2024", "2025", "2026",
)

# Numbers that make a password feel like a bit, not a credential.
MEME_NUMBERS: tuple[str, ...] = ("69", "420", "1337", "9000", "80085", "42")

# Keyboard walks, because someone always leans on the home row.
KEYBOARD_WALKS: tuple[str, ...] = ("qwerty", "asdf", "12345", "qazwsx", "zxcvbn", "1qaz2wsx")

# Small interjections that make a phrase read like a groupchat, not a vault.
BRO_SUFFIXES: tuple[str, ...] = ("bro", "fr", "lmao", "ngl", "istg", "sus", "uwu", "xd")


# --- individual rules -------------------------------------------------------


def rule_identity(word: str, rng: random.Random) -> Iterator[str]:
    yield word


def rule_capitalize(word: str, rng: random.Random) -> Iterator[str]:
    yield word.capitalize()
    yield word.upper()
    if len(word) > 1:
        yield word[0].lower() + word[1:].upper()  # tOGGLE-ish


def rule_leet(word: str, rng: random.Random) -> Iterator[str]:
    """Two flavours: swap every mappable char, and swap only vowels."""
    full = "".join(LEET_MAP.get(c.lower(), (c,))[0] if c.lower() in LEET_MAP else c for c in word)
    if full != word:
        yield full
    vowels = {"a", "e", "i", "o"}
    partial = "".join(
        LEET_MAP[c.lower()][0] if c.lower() in vowels and c.lower() in LEET_MAP else c
        for c in word
    )
    if partial != word and partial != full:
        yield partial


def rule_reverse(word: str, rng: random.Random) -> Iterator[str]:
    if len(word) > 2:
        yield word[::-1]


def rule_numbers(word: str, rng: random.Random) -> Iterator[str]:
    base = word.capitalize()
    for suffix in _sample(NUMBER_SUFFIXES, rng, 5):
        yield f"{base}{suffix}"


def rule_symbols(word: str, rng: random.Random) -> Iterator[str]:
    base = word.capitalize()
    for suffix in _sample(SYMBOL_SUFFIXES, rng, 4):
        yield f"{base}{suffix}"
    # symbol wrap, the "l33t forum tag" look
    yield f"_{word}_"
    yield f"xX{word.capitalize()}Xx"


def rule_meme_number(word: str, rng: random.Random) -> Iterator[str]:
    base = word.capitalize()
    for n in _sample(MEME_NUMBERS, rng, 2):
        yield f"{base}{n}"
        yield f"{base}{n}!"


def rule_keyboard(word: str, rng: random.Random) -> Iterator[str]:
    walk = rng.choice(KEYBOARD_WALKS)
    yield f"{word.capitalize()}{walk}"


def rule_bro(word: str, rng: random.Random) -> Iterator[str]:
    """Append a groupchat interjection. Pure 'are we for real' fuel."""
    for suffix in _sample(BRO_SUFFIXES, rng, 3):
        yield f"{word.capitalize()}_{suffix}"
        yield f"{word.capitalize()}{suffix.upper()}"


RULES: dict[str, Callable[[str, random.Random], Iterable[str]]] = {
    "identity": rule_identity,
    "capitalize": rule_capitalize,
    "leet": rule_leet,
    "reverse": rule_reverse,
    "numbers": rule_numbers,
    "symbols": rule_symbols,
    "meme": rule_meme_number,
    "keyboard": rule_keyboard,
    "bro": rule_bro,
}

# Sensible default rule set: enough breadth to be interesting, not so much that
# the output is 90% leet-of-a-dictionary-word noise.
DEFAULT_RULES: tuple[str, ...] = (
    "identity",
    "capitalize",
    "leet",
    "numbers",
    "symbols",
    "meme",
    "bro",
)


def mangle(word: str, rules: Iterable[str], rng: random.Random) -> Iterator[str]:
    """Apply the named rules to ``word``, yielding every produced variant."""
    for name in rules:
        fn = RULES.get(name)
        if fn is None:
            continue
        yield from fn(word, rng)


def _sample(items: tuple[str, ...], rng: random.Random, k: int) -> list[str]:
    """Deterministic sample of up to ``k`` items (order-stable per RNG state)."""
    if k >= len(items):
        return list(items)
    return rng.sample(list(items), k)

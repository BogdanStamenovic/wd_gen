"""The absurdity layer: template combinators, scoring, and the local LLM bridge.

Two independent sources of "are we for real bro" material:

  1. **Templates** (always available, deterministic under ``--seed``): stitch the
     themed banks together — and splice in profile tokens — into passphrases that
     read like a sentient Discord handle. No model, no network, no failure mode.

  2. **Local LLM** (optional): shell out to a small local model (``ollama`` by
     default, ``claude -p`` as a keyless alternative) and ask it for context-aware
     absurd passwords built from the profile. Best flavour, but it can be slow or
     absent — so it's strictly additive on top of the template floor.

``score()`` ranks everything by a blend of absurdity and memorability so the
strongest bits float to the top when the output is capped.
"""

from __future__ import annotations

import random
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator, Sequence

from . import banks

# Words we recognise as "themed" for scoring — a flat lowercase set of the banks.
_THEME_WORDS: frozenset[str] = frozenset(
    w.lower()
    for group in (banks.ADJECTIVES, banks.CREATURES, banks.ROLES, banks.OBJECTS, banks.VERBS)
    for w in group
)

_SEPARATORS: tuple[str, ...] = ("", "", "_", "-", ".")
_CAMEL_SPLIT = re.compile(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+|\d+")


# --- template combinators ---------------------------------------------------


def _pick(seq: Sequence[str], rng: random.Random) -> str:
    return rng.choice(list(seq))


def _sep(rng: random.Random) -> str:
    return rng.choice(_SEPARATORS)


def _tail(rng: random.Random) -> str:
    """Optional meme-number + symbol tail. Present most of the time."""
    parts = []
    if rng.random() < 0.7:
        parts.append(_pick(banks.MEME_NUMBERS, rng))
    if rng.random() < 0.5:
        parts.append(_pick(banks.SYMBOL_TAILS, rng))
    return "".join(parts)


# Each combinator takes (profile_tokens, rng) and returns one candidate string.
# profile_tokens may be empty — the templates degrade gracefully to pure banks.


def _t_adj_creature_role(tokens: Sequence[str], rng: random.Random) -> str:
    s = _sep(rng)
    return s.join(
        (_pick(banks.ADJECTIVES, rng), _pick(banks.CREATURES, rng), _pick(banks.ROLES, rng))
    ) + _tail(rng)


def _t_adj_object(tokens: Sequence[str], rng: random.Random) -> str:
    s = _sep(rng)
    return s.join(
        (_pick(banks.ADJECTIVES, rng), _pick(banks.OBJECTS, rng), _pick(banks.INTENSIFIERS, rng))
    ) + _tail(rng)


def _t_creature_verb_object(tokens: Sequence[str], rng: random.Random) -> str:
    s = _sep(rng)
    return s.join(
        (_pick(banks.CREATURES, rng), _pick(banks.VERBS, rng), _pick(banks.OBJECTS, rng))
    ) + _tail(rng)


def _t_bro_sentence(tokens: Sequence[str], rng: random.Random) -> str:
    s = _sep(rng)
    return s.join(
        (_pick(banks.ADJECTIVES, rng), _pick(banks.CREATURES, rng), _pick(banks.INTERJECTIONS, rng))
    ) + _tail(rng)


def _profile_word(tokens: Sequence[str], rng: random.Random) -> str:
    """A profile token, de-spaced and capitalised, or a bank fallback."""
    if tokens:
        raw = rng.choice(list(tokens))
        cleaned = re.sub(r"\s+", "", raw)
        return cleaned[:1].upper() + cleaned[1:] if cleaned else _pick(banks.CREATURES, rng)
    return _pick(banks.CREATURES, rng)


def _t_profile_adj_creature(tokens: Sequence[str], rng: random.Random) -> str:
    s = _sep(rng)
    return s.join(
        (_profile_word(tokens, rng), _pick(banks.ADJECTIVES, rng), _pick(banks.CREATURES, rng))
    ) + _tail(rng)


def _t_adj_profile_role(tokens: Sequence[str], rng: random.Random) -> str:
    s = _sep(rng)
    return s.join(
        (_pick(banks.ADJECTIVES, rng), _profile_word(tokens, rng), _pick(banks.ROLES, rng))
    ) + _tail(rng)


def _t_profile_verb_object(tokens: Sequence[str], rng: random.Random) -> str:
    s = _sep(rng)
    return s.join(
        (_profile_word(tokens, rng), _pick(banks.VERBS, rng), _pick(banks.OBJECTS, rng))
    ) + _tail(rng)


_TEMPLATES: tuple[Callable[[Sequence[str], random.Random], str], ...] = (
    _t_adj_creature_role,
    _t_adj_object,
    _t_creature_verb_object,
    _t_bro_sentence,
    _t_profile_adj_creature,
    _t_adj_profile_role,
    _t_profile_verb_object,
)


def absurd_candidates(
    tokens: Sequence[str], rng: random.Random, count: int
) -> Iterator[str]:
    """Yield ``count`` template-generated absurd passphrases."""
    for _ in range(count):
        template = rng.choice(_TEMPLATES)
        yield template(tokens, rng)


# --- username shaping -------------------------------------------------------

_USERNAME_STRIP = re.compile(r"[^A-Za-z0-9_.-]+")
_LEET_SIMPLE = str.maketrans({"a": "4", "e": "3", "i": "1", "o": "0", "s": "5"})


def to_usernames(candidate: str, rng: random.Random) -> Iterator[str]:
    """Reshape a candidate into handle-shaped variants (no spaces, url-safe)."""
    words = _CAMEL_SPLIT.findall(candidate) or [candidate]
    words = [w.lower() for w in words if w]
    if not words:
        return
    joiners = ("", "_", ".", "-")
    joiner = rng.choice(joiners)
    base = joiner.join(words)
    base = _USERNAME_STRIP.sub("", base).strip("._-")
    if not base:
        return
    yield base
    if rng.random() < 0.5:
        yield base.translate(_LEET_SIMPLE)
    if rng.random() < 0.6:
        yield f"{base}{rng.choice(banks.MEME_NUMBERS)}"
    if rng.random() < 0.3:
        yield f"the_real_{base}"
    if rng.random() < 0.3:
        yield f"x_{base}_x"


# --- scoring ----------------------------------------------------------------


def score(candidate: str) -> float:
    """Heuristic blend of absurdity and memorability. Higher = more unhinged."""
    if not candidate:
        return 0.0
    chunks = _CAMEL_SPLIT.findall(candidate)
    word_chunks = [c for c in chunks if c.isalpha()]
    lower_words = {c.lower() for c in word_chunks}

    s = 0.0
    # Passphrase structure: two or three word chunks is the memorable sweet spot.
    if len(word_chunks) >= 2:
        s += 2.0
    if len(word_chunks) >= 3:
        s += 1.0
    if len(word_chunks) >= 5:
        s -= 1.0  # too long to remember, back off
    # Themed vocabulary is the whole point.
    theme_hits = len(lower_words & _THEME_WORDS)
    s += min(theme_hits, 3) * 1.5
    # A meme number reads as a bit, not a credential.
    if re.search(r"(69|420|1337|9000|80085|666|777)", candidate):
        s += 1.0
    # Some punctuation, but a long symbol soup hurts memorability.
    symbols = sum(1 for c in candidate if not c.isalnum())
    if 1 <= symbols <= 3:
        s += 0.5
    elif symbols > 5:
        s -= 1.0
    # Length sweet spot for something you might actually retype.
    n = len(candidate)
    if 12 <= n <= 32:
        s += 1.0
    elif n < 6:
        s -= 1.0
    elif n > 40:
        s -= 1.5
    # Pure digit/symbol soup with no words: unmemorable.
    if not word_chunks:
        s -= 2.0
    # Internal whitespace: valid in a password, but form-hostile and less
    # handle-like — nudge it below the clean CamelCase equivalents.
    if " " in candidate:
        s -= 1.5
    return s


# --- local LLM bridge -------------------------------------------------------


class LLMError(Exception):
    """Raised when an LLM backend is requested but cannot be used."""


def _build_prompt(profile_desc: str, count: int, kind: str) -> str:
    noun = "usernames / handles" if kind == "usernames" else "passwords / passphrases"
    return (
        f"Generate exactly {count} absurd, memorable, over-the-top {noun}.\n"
        f"They should be the kind that make someone say 'are we for real bro'.\n"
        f"Use these facts about the target where they fit:\n{profile_desc}\n\n"
        "Rules:\n"
        "- One per line, nothing else. No numbering, no quotes, no commentary.\n"
        "- Mix real words into ridiculous combos; make them pronounceable/memorable.\n"
        "- Vary structure: passphrases, leetspeak, number and symbol tails.\n"
        + ("- No spaces; keep them url-safe handle-shaped.\n" if kind == "usernames" else "")
    )


# Reasoning/marker noise emitted by thinking models (Qwen3 etc.) and chatty
# preambles. Any line hitting this is not a credential.
_THINK_TAG = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_PROSE_MARKERS = re.compile(
    r"(?i)\b(thinking|done thinking|here are|sure|okay|let me|password|username|"
    r"complexity|leetspeak|symbols?|for example|purpose|note:|these)\b"
)


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks from a raw model dump."""
    return _THINK_TAG.sub("", text)


def _sanitize_line(line: str) -> str | None:
    line = line.strip()
    # Drop bullets/numbering like "1. ", "- ", "* ".
    line = re.sub(r"^\s*(?:\d+[.)]|[-*•]|>)\s*", "", line)
    line = line.strip().strip("`'\"*")
    if not line or len(line) > 64:
        return None
    # A credential is a single token: any internal whitespace means prose leaked.
    if any(ch.isspace() for ch in line):
        return None
    # Reasoning markers, ellipsis-only lines, and no-letter junk are not output.
    if _PROSE_MARKERS.search(line) or line.strip(".") == "" or not any(c.isalpha() for c in line):
        return None
    return line


def llm_lines(
    profile_desc: str,
    *,
    backend: str,
    model: str,
    count: int,
    kind: str,
    timeout: float,
    warn: Callable[[str], None],
) -> list[str]:
    """Ask a local LLM for absurd lines. Returns [] (with a warning) on any snag.

    This is best-effort by contract: the template floor always covers the count,
    so a missing binary, a cold model, or a timeout degrades to "no LLM flavour
    this run" rather than a hard failure.
    """
    prompt = _build_prompt(profile_desc, count, kind)
    if backend == "ollama":
        if shutil.which("ollama") is None:
            warn("llm: 'ollama' not on PATH; skipping LLM layer")
            return []
        cmd = ["ollama", "run", model]
    elif backend == "claude":
        if shutil.which("claude") is None:
            warn("llm: 'claude' not on PATH; skipping LLM layer")
            return []
        cmd = ["claude", "-p"]
    else:
        raise LLMError(f"unknown llm backend {backend!r}")

    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        warn(f"llm: {backend} timed out after {timeout:g}s; skipping LLM layer")
        return []
    except OSError as exc:
        warn(f"llm: could not run {backend}: {exc}; skipping LLM layer")
        return []

    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "no stderr"
        warn(f"llm: {backend} exited {proc.returncode}: {detail}; skipping LLM layer")
        return []

    out: list[str] = []
    for raw in _strip_thinking(proc.stdout).splitlines():
        cleaned = _sanitize_line(raw)
        if cleaned:
            out.append(cleaned)
    if not out:
        warn(f"llm: {backend} returned no usable lines; skipping LLM layer")
    return out

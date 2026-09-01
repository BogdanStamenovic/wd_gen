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

import json
import random
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Sequence

from . import banks

# Bogdan's box runs the model over ollama's HTTP API (reachable on the tailnet),
# so the default backend talks to it directly — no local ollama binary needed.
# Override with --llm-host or $OLLAMA_HOST.
DEFAULT_OLLAMA_HOST = "http://archserver:11434"

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


def _build_prompt(profile_desc: str, count: int, kind: str, style: str) -> str:
    noun = "usernames / handles" if kind == "usernames" else "passwords"
    if style == "chaos":
        return (
            f"Generate exactly {count} absurd, memorable, over-the-top {noun}.\n"
            f"The kind that make someone say 'are we for real bro'.\n"
            f"Use these facts about the target where they fit:\n{profile_desc}\n\n"
            "Rules:\n"
            "- One per line, nothing else. No numbering, no quotes, no commentary.\n"
            "- Mix real words into ridiculous combos; make them memorable.\n"
            "- Vary structure: leetspeak, number and symbol tails.\n"
            + ("- No spaces; url-safe handle-shaped.\n" if kind == "usernames" else "")
        )
    # realistic: OSINT credential-guessing for authorized CTF/security testing.
    if kind == "usernames":
        body = (
            "- Realistic handles this person would plausibly register: "
            "first+last, initials, nicknames, name+number, truncations, light leetspeak.\n"
            "- No spaces; url-safe (letters, digits, . _ - only).\n"
        )
    else:
        body = (
            "- Realistic passwords this person would plausibly choose from their own "
            "life: name/pet/keyword + a meaningful year or number, maybe one symbol, "
            "maybe light leetspeak (like Name2001!, pet+birthyear).\n"
            "- Keep them the kind a normal person actually picks, not random strings.\n"
        )
    return (
        f"You are helping with an AUTHORIZED CTF/OSINT exercise: produce a targeted "
        f"credential-guessing wordlist for this specific target.\n"
        f"Target facts:\n{profile_desc}\n\n"
        f"Generate exactly {count} plausible {noun}, most-likely-first.\n"
        "Rules:\n"
        "- One per line, nothing else. No numbering, no quotes, no commentary.\n"
        + body
    )


# Reasoning/marker noise emitted by thinking models (Qwen3 etc.). Multi-word
# prose is already rejected by the no-whitespace rule below; this only needs to
# catch BARE single-token reasoning artifacts ("Thinking...", "Okay", "Note").
# Deliberately narrow so it never eats a legit guess like "password123".
_THINK_TAG = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_MARKER_WORDS = frozenset(
    {"thinking", "done", "note", "answer", "output", "here", "sure", "okay",
     "certainly", "yes", "no", "passwords", "usernames", "wordlist"}
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
    # Ellipsis-only / no-letter junk, and bare reasoning-marker words.
    if line.strip(".") == "" or not any(c.isalpha() for c in line):
        return None
    if "".join(c for c in line.lower() if c.isalpha()) in _MARKER_WORDS:
        return None
    return line


def llm_complete(
    prompt: str,
    *,
    backend: str,
    model: str,
    host: str = DEFAULT_OLLAMA_HOST,
    timeout: float,
    warn: Callable[[str], None],
) -> str | None:
    """Run one prompt through an LLM backend, return the raw text or ``None``.

    The single shared entry point. ``ollama`` talks to a running ollama server
    over its HTTP API (``host``); ``claude`` shells out to ``claude -p``. Every
    failure mode (unreachable host, timeout, non-zero exit) becomes ``None`` plus
    a stderr warning, and ``<think>`` blocks are stripped so callers only see the
    answer. Best-effort by contract — no caller hard-fails on an absent LLM.
    """
    if backend == "ollama":
        return _ollama_generate(prompt, host=host, model=model, timeout=timeout, warn=warn)
    if backend == "claude":
        return _claude_generate(prompt, timeout=timeout, warn=warn)
    raise LLMError(f"unknown llm backend {backend!r}")


def _ollama_generate(
    prompt: str,
    *,
    host: str,
    model: str,
    timeout: float,
    warn: Callable[[str], None],
) -> str | None:
    """POST to ``{host}/api/generate`` (non-streaming), return the response text.

    ``think: false`` keeps the thinking-model reasoning out of the payload; the
    ``_strip_thinking`` pass is kept as a belt-and-braces fallback.
    """
    url = host.rstrip("/") + "/api/generate"
    payload = json.dumps(
        {"model": model, "prompt": prompt, "stream": False, "think": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()[:200] or exc.reason
        warn(f"llm: ollama at {host} returned {exc.code}: {detail}; skipping LLM layer")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        warn(f"llm: ollama at {host} unreachable ({reason}); skipping LLM layer")
        return None
    except (json.JSONDecodeError, ValueError):
        warn(f"llm: ollama at {host} returned unparseable JSON; skipping LLM layer")
        return None

    response = data.get("response") if isinstance(data, dict) else None
    if not response:
        warn(f"llm: ollama at {host} returned an empty response; skipping LLM layer")
        return None
    return _strip_thinking(response)


def _claude_generate(
    prompt: str,
    *,
    timeout: float,
    warn: Callable[[str], None],
) -> str | None:
    """Keyless fallback backend: shell out to ``claude -p``."""
    if shutil.which("claude") is None:
        warn("llm: 'claude' not on PATH; skipping LLM layer")
        return None
    try:
        proc = subprocess.run(
            ["claude", "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        warn(f"llm: claude timed out after {timeout:g}s; skipping LLM layer")
        return None
    except OSError as exc:
        warn(f"llm: could not run claude: {exc}; skipping LLM layer")
        return None
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "no stderr"
        warn(f"llm: claude exited {proc.returncode}: {detail}; skipping LLM layer")
        return None
    return _strip_thinking(proc.stdout)


def llm_lines(
    profile_desc: str,
    *,
    backend: str,
    model: str,
    host: str = DEFAULT_OLLAMA_HOST,
    count: int,
    kind: str,
    style: str = "realistic",
    timeout: float,
    warn: Callable[[str], None],
) -> list[str]:
    """Ask an LLM for candidate lines. Returns [] (with a warning) on any snag.

    Best-effort by contract: the deterministic engine always covers the count, so
    an unreachable host, a cold model, or a timeout degrades to "no LLM flavour
    this run" rather than a hard failure.
    """
    prompt = _build_prompt(profile_desc, count, kind, style)
    text = llm_complete(prompt, backend=backend, model=model, host=host, timeout=timeout, warn=warn)
    if text is None:
        return []

    out: list[str] = []
    for raw in text.splitlines():
        cleaned = _sanitize_line(raw)
        if cleaned:
            out.append(cleaned)
    if not out:
        warn(f"llm: {backend} returned no usable lines; skipping LLM layer")
    return out

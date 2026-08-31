"""Core orchestrator: profile + wordlist + rules + absurdity -> ranked output.

The pipeline, end to end:

    seeds  = profile tokens  (+ pairwise profile combos, high-signal)
           + bundled/base wordlist
    raw    = mangle(seed, rules)          for every seed
           + absurd template passphrases  (topped up to hit the target count)
           + local-LLM lines              (optional, best-effort flavour)
    shaped = raw                          in password mode
           | to_usernames(raw)            in username mode
    result = dedup(shaped), scored, sorted by absurdity/memorability, capped

Everything is driven by a passed-in RNG so a given ``--seed`` reproduces the
whole run bit for bit (the LLM layer aside, which is inherently non-deterministic
and documented as such).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from importlib.resources import files

from . import absurd
from .mangle import DEFAULT_RULES, mangle
from .profile import Profile

DEFAULT_COUNT = 5000
# Hard ceiling on absurd-template top-up attempts, so a fully saturated dedup
# set can never spin forever chasing an unreachable target.
_TOPUP_FACTOR = 8


class WdGenError(Exception):
    """Raised when wd_gen cannot complete generation."""


@dataclass
class Config:
    """Everything a single generation run needs."""

    profile: Profile = field(default_factory=Profile)
    wordlist: list[str] = field(default_factory=list)
    rules: Sequence[str] = DEFAULT_RULES
    count: int = DEFAULT_COUNT
    absurd_ratio: float = 0.6  # min fraction of output that must be absurd-template gold
    mode: str = "passwords"  # "passwords" | "usernames"
    min_len: int = 4
    max_len: int = 48
    use_llm: bool = False
    llm_backend: str = "ollama"
    llm_model: str = "JOSIEFIED-Qwen3:8b"
    llm_count: int = 40
    llm_timeout: float = 120.0


@dataclass
class Candidate:
    value: str
    score: float
    source: str  # "rule" | "absurd" | "llm"


def load_bundled_wordlist() -> list[str]:
    """Read the packaged generic base wordlist."""
    text = files("wd_gen.data").joinpath("wordlist.txt").read_text(encoding="utf-8")
    return _parse_wordlist(text)


def load_wordlist_file(path: str) -> list[str]:
    from pathlib import Path

    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise WdGenError(f"cannot read wordlist {path}: {exc}") from exc
    words = _parse_wordlist(text)
    if not words:
        raise WdGenError(f"wordlist {path} contained no usable words")
    return words


def _parse_wordlist(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        w = line.strip()
        if w and not w.startswith("#"):
            out.append(w)
    return out


def _seeds(profile: Profile, wordlist: Sequence[str]) -> list[str]:
    """Profile tokens first (highest signal), then pairwise profile combos,
    then the generic wordlist."""
    tokens = profile.tokens()
    seeds: list[str] = list(tokens)
    # Pairwise CamelCase combos of profile tokens — "Bogdan" + "NextJs" style.
    for i, a in enumerate(tokens):
        for b in tokens[i + 1 :]:
            ca = _camel(a)
            cb = _camel(b)
            seeds.append(ca + cb)
            seeds.append(cb + ca)
    seeds.extend(wordlist)
    return seeds


def _camel(word: str) -> str:
    cleaned = "".join(ch for ch in word if ch.isalnum())
    return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned


def generate(
    config: Config,
    rng: random.Random,
    *,
    progress: Callable[[str], None] | None = None,
    warn: Callable[[str], None] | None = None,
) -> list[Candidate]:
    """Run the full pipeline and return up to ``config.count`` ranked candidates."""
    _progress = progress or (lambda _m: None)
    _warn = warn or (lambda _m: None)

    if config.mode not in ("passwords", "usernames"):
        raise WdGenError(f"unknown mode {config.mode!r}")
    if config.count < 1:
        raise WdGenError("count must be >= 1")

    tokens = config.profile.tokens()
    seeds = _seeds(config.profile, config.wordlist)
    _progress(f"seeds: {len(seeds)} ({len(tokens)} from profile)")

    pool: dict[str, Candidate] = {}

    def add(value: str, source: str) -> None:
        value = value.strip()
        if not (config.min_len <= len(value) <= config.max_len):
            return
        s = absurd.score(value)
        if source == "llm":
            s += 1.0  # context-aware; nudge it up the ranking
        existing = pool.get(value)
        if existing is None or s > existing.score:
            pool[value] = Candidate(value=value, score=s, source=source)

    def emit(value: str, source: str) -> None:
        """Add a raw candidate, shaping to a username first when in that mode."""
        if config.mode == "usernames":
            for handle in absurd.to_usernames(value, rng):
                add(handle, source)
        else:
            add(value, source)

    # 1. Absurd template gold — generated in volume UP FRONT, not as gap-filler.
    #    This is the "are we for real bro" material and the whole point of the
    #    tool, so it must always be present in quantity regardless of how much
    #    the rule engine produces. Because absurd candidates score highest, this
    #    is what floats to the top of the capped, ranked output.
    absurd_target = max(1, int(config.count * config.absurd_ratio))
    attempts = 0
    max_attempts = max(absurd_target * _TOPUP_FACTOR, 2048)
    batch = max(256, absurd_target // 4)

    def absurd_hits() -> int:
        return sum(1 for c in pool.values() if c.source == "absurd")

    while absurd_hits() < absurd_target and attempts < max_attempts:
        for value in absurd.absurd_candidates(tokens, rng, batch):
            emit(value, "absurd")
        attempts += batch
    _progress(f"after absurd: {len(pool)} ({absurd_hits()} absurd)")

    # 2. Rule mangling over every seed — breadth/variety for the tail.
    for seed in seeds:
        for variant in mangle(seed, config.rules, rng):
            emit(variant, "rule")
    _progress(f"after rules: {len(pool)}")

    # 3. Optional local-LLM flavour (best-effort; never blocks the floor).
    if config.use_llm:
        _progress(f"llm: asking {config.llm_backend}:{config.llm_model} for ~{config.llm_count}")
        desc = _profile_description(config.profile)
        lines = absurd.llm_lines(
            desc,
            backend=config.llm_backend,
            model=config.llm_model,
            count=config.llm_count,
            kind=config.mode,
            timeout=config.llm_timeout,
            warn=_warn,
        )
        for line in lines:
            emit(line, "llm")
        _progress(f"llm: added, pool now {len(pool)}")

    # 4. Top up with more absurd templates until we hit the total target.
    target = config.count
    attempts = 0
    max_attempts = target * _TOPUP_FACTOR
    batch = max(256, target // 4)
    while len(pool) < target and attempts < max_attempts:
        for value in absurd.absurd_candidates(tokens, rng, batch):
            emit(value, "absurd")
        attempts += batch
    _progress(f"after top-up: {len(pool)} (target {target})")

    if len(pool) < target:
        _warn(
            f"produced {len(pool)} unique candidates, fewer than requested {target}; "
            "dedup saturated — widen the profile, rules, or length window for more"
        )

    # Rank by score; scramble within a score tier (deterministically) so the top
    # of the list is a varied mix, not an alphabetical run of the same template.
    import hashlib

    def _tiebreak(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()  # tiebreak, not security

    ranked = sorted(pool.values(), key=lambda c: (-c.score, _tiebreak(c.value)))
    return ranked[:target]


def _profile_description(profile: Profile) -> str:
    """Human-readable profile summary for the LLM prompt."""
    lines: list[str] = []
    labels = {
        "names": "owner/people",
        "org": "organisation",
        "framework": "framework/stack",
        "purpose": "purpose",
        "keywords": "keywords",
        "pets": "pets",
        "dates": "dates",
        "extras": "other",
    }
    for field_name, label in labels.items():
        vals = getattr(profile, field_name)
        if vals:
            lines.append(f"- {label}: {', '.join(vals)}")
    return "\n".join(lines) if lines else "- (no specific facts provided; go fully generic)"


def iter_values(candidates: Sequence[Candidate]) -> Iterator[str]:
    for c in candidates:
        yield c.value

"""Core orchestrator: target profile -> ranked credential candidates.

Two engines, chosen by ``Config.style``:

  * **realistic** (default) — the OSINT/CTF engine in ``perms``. Enumerates the
    plausible usernames and passwords the *target* would actually pick from their
    own name and facts (``first+last``, ``f.last``, ``name+year``, ``Name123!``,
    light leet). Ranked most-likely-first so the best guesses are tried first.

  * **chaos** — the absurd meme engine in ``absurd`` + generic rule mangling.
    The "are we for real bro" flavour: unhinged themed passphrases. Kept because
    it was the original ask, now behind ``--chaos``.

Both dedup, score, sort, and cap at ``Config.count``. Everything runs off the
passed-in RNG so ``--seed`` reproduces a run (the optional LLM layer aside).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from importlib.resources import files

from . import absurd, context, perms
from .mangle import DEFAULT_RULES, mangle
from .profile import Profile

DEFAULT_COUNT = 5000
# Hard ceiling on template top-up attempts, so a fully saturated dedup set can
# never spin forever chasing an unreachable target.
_TOPUP_FACTOR = 8


class WdGenError(Exception):
    """Raised when wd_gen cannot complete generation."""


@dataclass
class Config:
    """Everything a single generation run needs."""

    profile: Profile = field(default_factory=Profile)
    count: int = DEFAULT_COUNT
    mode: str = "passwords"  # "passwords" | "usernames"
    style: str = "realistic"  # "realistic" (OSINT) | "chaos" (absurd memes)
    min_len: int = 3
    max_len: int = 48
    year_range: tuple[int, int] = perms.DEFAULT_YEAR_RANGE
    # generic common-credential blending (realistic style)
    include_common: bool = True
    common_weight: float | None = None  # None = let context/LLM decide; else force
    # chaos-only knobs
    wordlist: list[str] = field(default_factory=list)
    rules: Sequence[str] = DEFAULT_RULES
    absurd_ratio: float = 0.6
    # local LLM (both styles)
    use_llm: bool = False
    llm_backend: str = "ollama"
    llm_model: str = "goekdenizguelmez/JOSIEFIED-Qwen3:8b"
    llm_host: str = absurd.DEFAULT_OLLAMA_HOST
    llm_count: int = 40
    llm_timeout: float = 120.0


@dataclass
class Candidate:
    value: str
    score: float
    source: str  # "perm" | "llm" | "absurd" | "rule"


def load_bundled_wordlist() -> list[str]:
    """Read the packaged generic base wordlist (used by chaos style)."""
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


def generate(
    config: Config,
    rng: random.Random,
    *,
    progress: Callable[[str], None] | None = None,
    warn: Callable[[str], None] | None = None,
) -> list[Candidate]:
    """Run the selected engine and return up to ``config.count`` ranked candidates."""
    _progress = progress or (lambda _m: None)
    _warn = warn or (lambda _m: None)

    if config.mode not in ("passwords", "usernames"):
        raise WdGenError(f"unknown mode {config.mode!r}")
    if config.style not in ("realistic", "chaos"):
        raise WdGenError(f"unknown style {config.style!r}")
    if config.count < 1:
        raise WdGenError("count must be >= 1")

    if config.style == "realistic":
        return _generate_realistic(config, rng, _progress, _warn)
    return _generate_chaos(config, rng, _progress, _warn)


# --- realistic (OSINT) engine ----------------------------------------------


def _generate_realistic(
    config: Config,
    rng: random.Random,
    progress: Callable[[str], None],
    warn: Callable[[str], None],
) -> list[Candidate]:
    is_username = config.mode == "usernames"
    base_tokens = perms.personal_tokens(config.profile)
    hot_numbers = frozenset(perms.expand_dates(config.profile))
    progress(f"target tokens: {len(base_tokens)} -> {base_tokens[:8]}")

    pool: dict[str, Candidate] = {}

    def add(value: str, source: str, score: float | None = None) -> None:
        value = value.strip()
        if not (config.min_len <= len(value) <= config.max_len):
            return
        if score is None:
            score = perms.plausibility(value, base_tokens, hot_numbers)
            if source == "llm":
                score += 0.5  # the model saw the whole profile; nudge its picks up
        cur = pool.get(value)
        if cur is None or score > cur.score:
            pool[value] = Candidate(value=value, score=score, source=source)

    if is_username:
        for u in perms.iter_usernames(config.profile, year_range=config.year_range):
            add(u, "perm")
    else:
        for p in perms.iter_passwords(config.profile, rng, year_range=config.year_range):
            add(p, "perm")
    progress(f"after permutations: {len(pool)}")

    # Generic common credentials (admin123, password1, admin/root...) — the class
    # a targeted profile never covers on its own. How heavily they blend in, and
    # whether they belong at all, is decided by the context (LLM or regex).
    if config.include_common:
        policy = _resolve_policy(config, is_username, progress, warn)
        _inject_common(policy, is_username, config, add)
        progress(f"after common creds: {len(pool)}")

    if config.use_llm:
        _run_llm(config, pool, add, progress, warn)

    if not pool:
        warn(
            "no candidates — give the target's name and facts "
            "(--owner/--nick/--keyword/--birthday ...); realistic mode needs a target"
        )

    ranked = sorted(pool.values(), key=lambda c: (-c.score, _tiebreak(c.value)))
    if len(ranked) < config.count:
        warn(
            f"produced {len(ranked)} unique candidates, fewer than requested {config.count}; "
            "widen the profile, --years range, or length window for more"
        )
    return ranked[: config.count]


def _resolve_policy(
    config: Config,
    is_username: bool,
    progress: Callable[[str], None],
    warn: Callable[[str], None],
) -> context.ContextPolicy:
    """Decide the common-credential policy: manual override > LLM > regex rules."""
    if config.common_weight is not None:
        policy = context.ContextPolicy(
            category="manual",
            common_weight=max(0.0, config.common_weight),
            note=f"forced --common-weight {config.common_weight:g}",
        )
    elif config.use_llm:
        policy = context.llm_policy(
            config.profile,
            is_username=is_username,
            backend=config.llm_backend,
            model=config.llm_model,
            host=config.llm_host,
            timeout=config.llm_timeout,
            warn=warn,
        )
    else:
        policy = context.classify(config.profile, is_username=is_username)
    progress(f"context policy: {policy.category} weight={policy.common_weight:.2f} — {policy.note}")
    return policy


def _inject_common(
    policy: context.ContextPolicy,
    is_username: bool,
    config: Config,
    add: Callable[..., None],
) -> None:
    """Blend frequency-ranked common creds + context seeds in per ``policy``."""
    if not policy.suppressed:
        creds = context.common_credentials(is_username=is_username)
        total = len(creds)
        for rank, cred in enumerate(creds):
            add(cred, "common", context.common_score(rank, total, policy))
    # Context-specific seeds (an SSID, a service word) ride along as strong common
    # hits even when the generic list is suppressed.
    seed_weight = max(policy.common_weight, 0.8)
    for seed in policy.seeds:
        add(seed, "common", policy.common_bias + seed_weight * 6.0)


# --- chaos (absurd) engine --------------------------------------------------


def _generate_chaos(
    config: Config,
    rng: random.Random,
    progress: Callable[[str], None],
    warn: Callable[[str], None],
) -> list[Candidate]:
    tokens = config.profile.tokens()
    seeds = _chaos_seeds(config.profile, config.wordlist)
    progress(f"seeds: {len(seeds)} ({len(tokens)} from profile)")

    pool: dict[str, Candidate] = {}

    def add(value: str, source: str) -> None:
        value = value.strip()
        if not (config.min_len <= len(value) <= config.max_len):
            return
        s = absurd.score(value)
        if source == "llm":
            s += 1.0
        cur = pool.get(value)
        if cur is None or s > cur.score:
            pool[value] = Candidate(value=value, score=s, source=source)

    def emit(value: str, source: str) -> None:
        if config.mode == "usernames":
            for handle in absurd.to_usernames(value, rng):
                add(handle, source)
        else:
            add(value, source)

    absurd_target = max(1, int(config.count * config.absurd_ratio))
    _fill_absurd(pool, emit, tokens, rng, absurd_target)
    progress(f"after absurd: {len(pool)}")

    for seed in seeds:
        for variant in mangle(seed, config.rules, rng):
            emit(variant, "rule")
    progress(f"after rules: {len(pool)}")

    if config.use_llm:
        _run_llm(config, pool, emit, progress, warn)

    _fill_absurd(pool, emit, tokens, rng, config.count)
    progress(f"after top-up: {len(pool)}")

    ranked = sorted(pool.values(), key=lambda c: (-c.score, _tiebreak(c.value)))
    if len(ranked) < config.count:
        warn(f"produced {len(ranked)} unique candidates, fewer than requested {config.count}")
    return ranked[: config.count]


def _fill_absurd(
    pool: dict[str, Candidate],
    emit: Callable[[str, str], None],
    tokens: Sequence[str],
    rng: random.Random,
    target: int,
) -> None:
    """Emit absurd templates until the pool reaches ``target`` (or tries run out)."""
    attempts = 0
    max_attempts = max(target * _TOPUP_FACTOR, 2048)
    batch = max(256, target // 4)
    while len(pool) < target and attempts < max_attempts:
        for value in absurd.absurd_candidates(tokens, rng, batch):
            emit(value, "absurd")
        attempts += batch


def _chaos_seeds(profile: Profile, wordlist: Sequence[str]) -> list[str]:
    tokens = profile.tokens()
    seeds: list[str] = list(tokens)
    for i, a in enumerate(tokens):
        for b in tokens[i + 1 :]:
            ca, cb = _camel(a), _camel(b)
            seeds.append(ca + cb)
            seeds.append(cb + ca)
    seeds.extend(wordlist)
    return seeds


def _camel(word: str) -> str:
    cleaned = "".join(ch for ch in word if ch.isalnum())
    return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned


# --- shared helpers ---------------------------------------------------------


def _run_llm(
    config: Config,
    pool: dict[str, Candidate],
    add: Callable[[str, str], None],
    progress: Callable[[str], None],
    warn: Callable[[str], None],
) -> None:
    where = config.llm_host if config.llm_backend == "ollama" else config.llm_backend
    progress(f"llm: asking {config.llm_model} @ {where} for ~{config.llm_count}")
    desc = _profile_description(config.profile)
    lines = absurd.llm_lines(
        desc,
        backend=config.llm_backend,
        model=config.llm_model,
        host=config.llm_host,
        count=config.llm_count,
        kind=config.mode,
        style=config.style,
        timeout=config.llm_timeout,
        warn=warn,
    )
    for line in lines:
        add(line, "llm")
    progress(f"llm: added, pool now {len(pool)}")


def _tiebreak(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()  # tiebreak, not security


def _profile_description(profile: Profile) -> str:
    """Human-readable profile summary for the LLM prompt."""
    lines: list[str] = []
    labels = {
        "names": "full name",
        "org": "employer/organisation",
        "framework": "tech/interests",
        "purpose": "context",
        "keywords": "keywords",
        "pets": "pets",
        "dates": "significant dates",
        "extras": "other (partner, city, hobbies)",
    }
    for field_name, label in labels.items():
        vals = getattr(profile, field_name)
        if vals:
            lines.append(f"- {label}: {', '.join(vals)}")
    return "\n".join(lines) if lines else "- (no specific facts provided)"


def iter_values(candidates: Sequence[Candidate]) -> Iterator[str]:
    for c in candidates:
        yield c.value

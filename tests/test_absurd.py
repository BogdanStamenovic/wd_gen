from __future__ import annotations

import random

from wd_gen import absurd
from wd_gen.absurd import _sanitize_line, _strip_thinking, llm_lines


def test_sanitize_drops_thinking_and_prose() -> None:
    noise = [
        "Thinking...",
        "...done thinking.",
        "symbols for complexity.",
        "leetspeak or symbols.",
        "purpose is chaos infra.",
        "Here are 5 passwords:",
        "1. realone",  # numbering stripped -> 'realone' kept
        "- MoistGoose69!",
        "ZombotKaboomBogdan@ArchServer$",
        "has spaces here",
        "....",
    ]
    kept = [s for s in (_sanitize_line(x) for x in noise) if s]
    assert "ZombotKaboomBogdan@ArchServer$" in kept
    assert "MoistGoose69!" in kept
    assert "realone" in kept
    assert all(" " not in k for k in kept)
    assert not any("thinking" in k.lower() for k in kept)


def test_strip_thinking_tags() -> None:
    raw = "before<think>secret reasoning\nmore</think>after"
    assert "reasoning" not in _strip_thinking(raw)


def test_llm_lines_unreachable_host_is_graceful() -> None:
    warnings: list[str] = []
    out = llm_lines(
        "- owner: x",
        backend="ollama",
        model="whatever:0b",
        host="http://127.0.0.1:1",  # nothing listens here -> connection refused
        count=5,
        kind="passwords",
        timeout=5.0,
        warn=warnings.append,
    )
    # An unreachable ollama host must degrade to [] with a warning, never raise.
    assert out == []
    assert warnings
    assert "unreachable" in warnings[-1].lower()


def test_absurd_candidates_use_profile_tokens() -> None:
    rng = random.Random(0)
    got = "\n".join(absurd.absurd_candidates(["Zorptron"], rng, 400))
    assert "Zorptron" in got

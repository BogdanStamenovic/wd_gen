from __future__ import annotations

import random

from wd_gen import absurd
from wd_gen.generate import Config, generate, load_bundled_wordlist
from wd_gen.mangle import mangle
from wd_gen.profile import Profile


def _cfg(**kw) -> Config:
    base = {
        "profile": Profile(names=["Bogdan"], framework=["NextJs"]),
        "wordlist": load_bundled_wordlist(),
        "count": 1000,
    }
    base.update(kw)
    return Config(**base)


def test_generate_hits_target_count() -> None:
    out = generate(_cfg(count=5000), random.Random(1))
    assert len(out) == 5000
    assert len({c.value for c in out}) == 5000


def test_generate_is_deterministic_under_seed() -> None:
    a = generate(_cfg(count=800), random.Random(5))
    b = generate(_cfg(count=800), random.Random(5))
    assert [c.value for c in a] == [c.value for c in b]


def test_results_sorted_by_score_desc() -> None:
    out = generate(_cfg(count=500), random.Random(2))
    scores = [c.score for c in out]
    assert scores == sorted(scores, reverse=True)


def test_profile_tokens_appear_in_output() -> None:
    out = generate(_cfg(count=2000), random.Random(3))
    joined = "\n".join(c.value for c in out).lower()
    assert "bogdan" in joined


def test_bundled_wordlist_nonempty() -> None:
    assert len(load_bundled_wordlist()) > 100


def test_mangle_produces_variants() -> None:
    rng = random.Random(0)
    variants = set(mangle("dragon", ["leet", "numbers", "symbols"], rng))
    assert len(variants) > 3
    assert any(any(ch.isdigit() for ch in v) for v in variants)


def test_score_prefers_passphrase_over_single_word() -> None:
    assert absurd.score("MoistHamsterOverlord69") > absurd.score("dragon")


def test_username_shaping_has_no_spaces() -> None:
    rng = random.Random(1)
    handles = list(absurd.to_usernames("Moist Hamster Overlord", rng))
    assert handles
    assert all(" " not in h for h in handles)


def test_empty_profile_still_generates() -> None:
    cfg = Config(profile=Profile(), wordlist=load_bundled_wordlist(), count=1000)
    out = generate(cfg, random.Random(1))
    assert len(out) == 1000


def test_candidate_sources_are_known() -> None:
    out = generate(_cfg(count=1500), random.Random(4))
    assert {c.source for c in out} <= {"rule", "absurd", "llm"}

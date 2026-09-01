from __future__ import annotations

import random

from wd_gen.generate import Config, generate, load_bundled_wordlist
from wd_gen.perms import iter_passwords, iter_usernames, plausibility
from wd_gen.profile import Profile


def _target() -> Profile:
    return Profile(names=["Bogdan Stamenovix"], pets=["goose"], dates=["2001"], keywords=["pigion"])


def _cfg(**kw) -> Config:
    base: dict = {"profile": _target(), "count": 2000}
    base.update(kw)
    return Config(**base)


# --- realistic username shapes (the OSINT core) ----------------------------


def test_usernames_include_expected_osint_shapes() -> None:
    us = set(iter_usernames(_target()))
    # The systematic handles a real person would register.
    for expected in ("bogdan", "stamenovix", "bogdans", "bstamenovix", "bogdanstamenovix"):
        assert expected in us, expected


def test_usernames_have_separators_and_leet() -> None:
    us = set(iter_usernames(_target()))
    assert "bogdan.stamenovix" in us or "bogdan_stamenovix" in us
    assert any(ch.isdigit() for u in us for ch in u)  # leet/number variants exist


def test_username_name_plus_year() -> None:
    us = set(iter_usernames(_target()))
    assert any(u.startswith("bogdan") and "2001" in u for u in us)


# --- realistic password shapes ---------------------------------------------


def test_passwords_include_name_year_and_symbol_shapes() -> None:
    pw = set(iter_passwords(_target(), random.Random(0)))
    assert "Bogdan2001" in pw
    assert "Bogdan123" in pw
    assert any(p.startswith("Bogdan") and p.endswith("!") for p in pw)
    assert "goose2001" in pw or "Goose2001" in pw


def test_password_combos_of_tokens() -> None:
    pw = set(iter_passwords(_target(), random.Random(0)))
    assert any("goose" in p.lower() and "bogdan" in p.lower() for p in pw)


# --- ranking: most-likely first --------------------------------------------


def test_plausibility_prefers_common_over_soup() -> None:
    toks = ["bogdan"]
    assert plausibility("Bogdan2001", toks) > plausibility("B0gd4n@#$!x", toks)
    assert plausibility("bogdan123", toks) > plausibility("stamenovix", ["stamenovix"]) - 5


def test_realistic_top_is_name_derived(capsys=None) -> None:
    out = generate(_cfg(count=200), random.Random(1))
    top = [c.value.lower() for c in out[:50]]
    assert any("bogdan" in v or "stamenovix" in v or "goose" in v for v in top)


# --- pipeline properties ----------------------------------------------------


def test_generate_deterministic_under_seed() -> None:
    a = generate(_cfg(count=1000), random.Random(5))
    b = generate(_cfg(count=1000), random.Random(5))
    assert [c.value for c in a] == [c.value for c in b]


def test_results_sorted_by_score_desc() -> None:
    out = generate(_cfg(count=500), random.Random(2))
    scores = [c.score for c in out]
    assert scores == sorted(scores, reverse=True)


def test_realistic_reaches_reasonable_volume() -> None:
    out = generate(_cfg(count=5000), random.Random(3))
    assert len(out) > 3000  # rich profile fills thousands of plausible guesses
    assert len({c.value for c in out}) == len(out)


def test_empty_profile_without_common_is_empty_with_warning() -> None:
    warnings: list[str] = []
    cfg = Config(profile=Profile(), count=100, include_common=False)
    out = generate(cfg, random.Random(1), warn=warnings.append)
    assert out == []
    assert warnings


def test_empty_profile_still_yields_common_creds() -> None:
    # With no target, the generic common list is a useful standalone wordlist.
    cfg = Config(profile=Profile(), count=100)
    out = generate(cfg, random.Random(1))
    assert out
    assert all(c.source == "common" for c in out)
    assert "123456" in {c.value for c in out}


# --- chaos mode still works -------------------------------------------------


def test_chaos_mode_hits_target_and_is_absurd() -> None:
    cfg = Config(profile=_target(), count=3000, style="chaos", wordlist=load_bundled_wordlist())
    out = generate(cfg, random.Random(1))
    assert len(out) == 3000
    assert {c.source for c in out} <= {"absurd", "rule", "llm"}


def test_bundled_wordlist_nonempty() -> None:
    assert len(load_bundled_wordlist()) > 100

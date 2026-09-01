from __future__ import annotations

import random

from wd_gen import context
from wd_gen.generate import Config, generate
from wd_gen.profile import Profile


def _gen(profile: Profile, **kw) -> list:
    base: dict = {"profile": profile, "count": 300}
    base.update(kw)
    return generate(Config(**base), random.Random(1))


# --- classification ---------------------------------------------------------


def test_classify_categories() -> None:
    cases = {
        "router admin login page": "admin",
        "office wifi wpa2 key": "wifi",
        "instagram handle": "social",
        "corporate outlook email": "corporate",
        "nothing in particular": "generic",
    }
    for text, expected in cases.items():
        pol = context.classify(Profile(purpose=[text]), is_username=False)
        assert pol.category == expected, (text, pol.category)


def test_social_username_suppresses_common() -> None:
    pol = context.classify(Profile(purpose=["instagram username"]), is_username=True)
    assert pol.category == "social"
    assert pol.suppressed


def test_social_password_still_blends_common() -> None:
    pol = context.classify(Profile(purpose=["instagram password"]), is_username=False)
    assert not pol.suppressed


def test_wifi_and_admin_outrank_targeted() -> None:
    wifi = context.classify(Profile(purpose=["home wifi key"]), is_username=False)
    admin = context.classify(Profile(purpose=["admin panel"]), is_username=True)
    assert wifi.common_weight > 1.4
    assert admin.common_weight > 1.4


# --- common_score -----------------------------------------------------------


def test_common_score_ranks_by_frequency() -> None:
    pol = context.ContextPolicy(common_weight=1.0)
    assert context.common_score(0, 100, pol) > context.common_score(99, 100, pol)


def test_common_score_scales_with_weight() -> None:
    hi = context.ContextPolicy(common_weight=1.6)
    lo = context.ContextPolicy(common_weight=0.5)
    assert context.common_score(0, 100, hi) > context.common_score(0, 100, lo)


def test_common_lists_load() -> None:
    assert "admin123" in context.load_common_passwords()
    assert "admin" in context.load_common_usernames()


# --- generation integration -------------------------------------------------


def _target() -> Profile:
    return Profile(names=["Bogdan Stamenovix"], dates=["2001"], pets=["goose"])


def test_generic_password_run_includes_common_unrelated() -> None:
    out = _gen(_target())
    values = {c.value for c in out}
    # The whole point: unrelated common passwords are present alongside targeted.
    assert values & {"123456", "password", "admin123", "password1"}
    assert any(c.source == "perm" for c in out)
    assert any(c.source == "common" for c in out)


def test_wifi_context_puts_common_on_top() -> None:
    out = _gen(Profile(names=["Bogdan"], purpose=["office wifi wpa2 key"]))
    top = out[:5]
    assert all(c.source == "common" for c in top), [c.value for c in top]


def test_social_username_run_has_no_common() -> None:
    out = _gen(Profile(names=["Bogdan Stamenovix"], purpose=["instagram username"]), mode="usernames")
    assert out
    assert all(c.source != "common" for c in out)


def test_no_common_flag_disables_injection() -> None:
    out = _gen(_target(), include_common=False)
    assert out
    assert all(c.source != "common" for c in out)


def test_common_weight_override_forces_ranking() -> None:
    hi = _gen(_target(), common_weight=2.0)
    assert all(c.source == "common" for c in hi[:5])
    zero = _gen(_target(), common_weight=0.0)
    assert all(c.source != "common" for c in zero)


def test_admin_username_ranks_default_handles_first() -> None:
    out = _gen(Profile(names=["Bogdan"], purpose=["router admin login"]), mode="usernames")
    assert out[0].value in {"admin", "root", "administrator"}


def test_seeds_are_injected() -> None:
    pol = context.ContextPolicy(category="wifi", common_weight=1.5, seeds=["myssidword"])
    pool: dict = {}

    def add(value, source, score=None):
        pool[value] = (source, score)

    import importlib

    gen_mod = importlib.import_module("wd_gen.generate")
    gen_mod._inject_common(pol, False, Config(profile=Profile()), add)
    assert "myssidword" in pool

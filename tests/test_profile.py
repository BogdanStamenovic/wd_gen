from __future__ import annotations

import json

import pytest

from wd_gen.profile import Profile, ProfileError


def test_simple_format(tmp_path) -> None:
    p = tmp_path / "target.profile"
    p.write_text(
        "# a comment\n"
        "owner: Bogdan Stamenovic\n"
        "framework: Next.js, FastAPI\n"
        "keywords: pigion, archserver\n",
        encoding="utf-8",
    )
    prof = Profile.load(p)
    assert "Bogdan Stamenovic" in prof.names
    assert "Next.js" in prof.framework and "FastAPI" in prof.framework
    assert "pigion" in prof.keywords


def test_json_format(tmp_path) -> None:
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"owner": ["Ada"], "framework": "Rust", "unknown": "x"}), encoding="utf-8")
    prof = Profile.load(p)
    assert prof.names == ["Ada"]
    assert prof.framework == ["Rust"]
    assert "x" in prof.extras  # unknown key routed to extras


def test_aliases_and_tokens() -> None:
    prof = Profile.from_mapping({"person": "Bo", "stack": "Go", "tags": "cli, tool"})
    tokens = prof.tokens()
    assert "Bo" in tokens and "Go" in tokens and "cli" in tokens


def test_dedup_in_tokens() -> None:
    prof = Profile(names=["Bo", "bo"], keywords=["Bo"])
    assert prof.tokens().count("Bo") + prof.tokens().count("bo") == 1


def test_merge() -> None:
    a = Profile(names=["A"])
    b = Profile(names=["B"], org=["X"])
    merged = a.merge(b)
    assert merged.names == ["A", "B"] and merged.org == ["X"]


def test_bad_simple_line_raises(tmp_path) -> None:
    p = tmp_path / "bad.profile"
    p.write_text("this line has no colon\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        Profile.load(p)


def test_missing_file_raises() -> None:
    with pytest.raises(ProfileError):
        Profile.load("/no/such/profile")

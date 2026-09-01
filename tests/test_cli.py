from __future__ import annotations

import json

import pytest

from wd_gen.absurd import DEFAULT_OLLAMA_HOST
from wd_gen.cli import _default_llm_host, main


def test_default_llm_host_uses_env(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert _default_llm_host() == DEFAULT_OLLAMA_HOST
    monkeypatch.setenv("OLLAMA_HOST", "myhost:9999")
    assert _default_llm_host() == "http://myhost:9999"  # bare host:port normalised
    monkeypatch.setenv("OLLAMA_HOST", "https://secure:443")
    assert _default_llm_host() == "https://secure:443"  # explicit scheme preserved


def test_version(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "wd_gen" in capsys.readouterr().out


def test_list_rules(capsys) -> None:
    assert main(["--list-rules"]) == 0
    err = capsys.readouterr().err
    assert "leet" in err and "bro" in err


def test_basic_passwords_clean_stdout(capsys) -> None:
    rc = main(["--count", "500", "--seed", "1", "--owner", "Bogdan Stamenovix", "--birthday", "2001"])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln]
    assert len(lines) == 500
    assert "warning" not in captured.out.lower()
    assert len(set(lines)) == len(lines)
    # realistic: the target's own name shows up near the top
    assert any("bogdan" in ln.lower() or "stamenovix" in ln.lower() for ln in lines[:50])


def test_seed_is_reproducible(capsys) -> None:
    main(["--count", "300", "--seed", "42", "--owner", "Ada Lovelace"])
    first = capsys.readouterr().out
    main(["--count", "300", "--seed", "42", "--owner", "Ada Lovelace"])
    assert first == capsys.readouterr().out


def test_usernames_are_handle_shaped(capsys) -> None:
    rc = main(["--usernames", "--count", "300", "--seed", "7", "--owner", "Bogdan Stamenovix"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert lines
    for ln in lines:
        assert " " not in ln
        assert all(c.isalnum() or c in "_.-" for c in ln), ln


def test_json_output_parses_and_sorted(capsys) -> None:
    rc = main(["--json", "--count", "80", "--seed", "3", "--owner", "Grace Hopper", "--birthday", "1906"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert {"value", "score", "source"} <= data[0].keys()
    scores = [d["score"] for d in data]
    assert scores == sorted(scores, reverse=True)


def test_length_window_respected(capsys) -> None:
    main(["--count", "200", "--seed", "9", "--min-len", "10", "--max-len", "16",
          "--owner", "Bogdan Stamenovix", "--birthday", "2001"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert lines
    for ln in lines:
        assert 10 <= len(ln) <= 16


def test_chaos_flag(capsys) -> None:
    rc = main(["--chaos", "--count", "800", "--seed", "1", "--owner", "Bogdan"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(lines) == 800


def test_years_flag_parses(capsys) -> None:
    rc = main(["--count", "3000", "--seed", "1", "--owner", "Bogdan Stamenovix", "--years", "1995-2005"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1999" in out or "2001" in out


def test_bad_years_is_usage_error(capsys) -> None:
    assert main(["--years", "nope"]) == 2
    assert "--years" in capsys.readouterr().err


def test_unknown_rule_is_usage_error(capsys) -> None:
    assert main(["--chaos", "--rules", "leet,bogus"]) == 2
    assert "unknown rule" in capsys.readouterr().err


def test_bad_count_is_error(capsys) -> None:
    assert main(["--count", "0", "--owner", "x"]) == 1
    assert "count must be" in capsys.readouterr().err


def test_missing_wordlist_is_error(capsys) -> None:
    assert main(["--wordlist", "/no/such/file.txt", "--owner", "x"]) == 1
    assert "cannot read wordlist" in capsys.readouterr().err


def test_empty_profile_warns(capsys) -> None:
    main(["--count", "10"])
    assert "no target facts" in capsys.readouterr().err

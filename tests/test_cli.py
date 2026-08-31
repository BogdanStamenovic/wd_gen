from __future__ import annotations

import json

import pytest

from wd_gen.cli import main


def test_version(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    out = capsys.readouterr().out
    assert "wd_gen" in out


def test_list_rules(capsys) -> None:
    assert main(["--list-rules"]) == 0
    err = capsys.readouterr().err
    assert "leet" in err and "bro" in err


def test_basic_passwords_count_and_clean_stdout(capsys) -> None:
    rc = main(["--count", "500", "--seed", "1", "--owner", "Bogdan", "--framework", "NextJs"])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln]
    assert len(lines) == 500
    # stdout is pure output: no warnings/progress leaked in.
    assert "warning" not in captured.out.lower()
    # unique
    assert len(set(lines)) == len(lines)


def test_seed_is_reproducible(capsys) -> None:
    main(["--count", "200", "--seed", "42", "--owner", "Ada"])
    first = capsys.readouterr().out
    main(["--count", "200", "--seed", "42", "--owner", "Ada"])
    second = capsys.readouterr().out
    assert first == second


def test_seed_differs_between_seeds(capsys) -> None:
    main(["--count", "200", "--seed", "1", "--owner", "Ada"])
    a = capsys.readouterr().out
    main(["--count", "200", "--seed", "2", "--owner", "Ada"])
    b = capsys.readouterr().out
    assert a != b


def test_usernames_are_handle_shaped(capsys) -> None:
    rc = main(["--usernames", "--count", "300", "--seed", "7", "--owner", "Bogdan"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(lines) == 300
    for ln in lines:
        assert " " not in ln
        assert all(c.isalnum() or c in "_.-" for c in ln), ln


def test_json_output_parses(capsys) -> None:
    rc = main(["--json", "--count", "50", "--seed", "3", "--owner", "Grace"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 50
    assert {"value", "score", "source"} <= data[0].keys()
    # sorted by score descending
    scores = [d["score"] for d in data]
    assert scores == sorted(scores, reverse=True)


def test_length_window_respected(capsys) -> None:
    main(["--count", "300", "--seed", "9", "--min-len", "10", "--max-len", "20", "--owner", "Bo"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert lines
    for ln in lines:
        assert 10 <= len(ln) <= 20


def test_unknown_rule_is_usage_error(capsys) -> None:
    assert main(["--rules", "leet,bogus"]) == 2
    assert "unknown rule" in capsys.readouterr().err


def test_bad_count_is_error(capsys) -> None:
    assert main(["--count", "0"]) == 1
    assert "count must be" in capsys.readouterr().err


def test_missing_wordlist_is_error(capsys) -> None:
    assert main(["--wordlist", "/no/such/file.txt"]) == 1
    assert "cannot read wordlist" in capsys.readouterr().err

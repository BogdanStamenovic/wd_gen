"""Command-line interface for wd_gen.

Keeps stdout clean: only the generated passwords/usernames (or the JSON array)
go to stdout, one per line, so it pipes straight into a file or another tool.
All progress, warnings, and errors go to stderr.

Exit codes: 0 success, 1 generation failed, 2 usage error / user aborted.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from typing import NoReturn

from . import __version__
from .generate import (
    Config,
    WdGenError,
    generate,
    load_bundled_wordlist,
    load_wordlist_file,
)
from .mangle import DEFAULT_RULES, RULES
from .profile import Profile, ProfileError


class _UsageError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="wd_gen",
        description="Generate absurd, memorable passwords and usernames from a target profile.",
        epilog="Give it the most info you can (--owner, --framework, --purpose ...); "
        "the more it knows, the more unhinged and pointed the output gets.",
    )

    parser.add_argument(
        "-n", "--count", type=int, default=5000,
        help="how many candidates to emit (default: 5000)",
    )
    parser.add_argument(
        "-u", "--usernames", action="store_true",
        help="generate usernames/handles instead of passwords",
    )

    prof = parser.add_argument_group("profile (who/what this is for)")
    prof.add_argument("--profile", metavar="FILE", help="load a profile file (JSON or simple 'field: a, b')")
    prof.add_argument("--owner", action="append", metavar="NAME", help="owner/person name (repeatable, comma-ok)")
    prof.add_argument("--org", action="append", metavar="ORG", help="organisation/company (repeatable)")
    prof.add_argument("--framework", action="append", metavar="TECH", help="framework/stack (repeatable)")
    prof.add_argument("--purpose", action="append", metavar="TEXT", help="what it's for (repeatable)")
    prof.add_argument("--keyword", action="append", metavar="WORD", help="freeform keyword (repeatable)")
    prof.add_argument("--pet", action="append", metavar="NAME", help="pet name (repeatable)")
    prof.add_argument("--date", action="append", metavar="D", help="significant date/year, e.g. 2026 (repeatable)")
    prof.add_argument("--extra", action="append", metavar="WORD", help="any other trivia (repeatable)")

    gen = parser.add_argument_group("generation")
    gen.add_argument("--wordlist", metavar="FILE", help="use a custom base wordlist instead of the bundled one")
    gen.add_argument("--rules", metavar="LIST", help=f"comma list of rules (default: {','.join(DEFAULT_RULES)})")
    gen.add_argument("--list-rules", action="store_true", help="print available mangling rules and exit")
    gen.add_argument("--min-len", type=int, default=4, help="drop candidates shorter than this (default: 4)")
    gen.add_argument("--max-len", type=int, default=48, help="drop candidates longer than this (default: 48)")
    gen.add_argument("--seed", type=int, help="RNG seed for reproducible output")

    llm = parser.add_argument_group("local LLM layer (optional, best-effort)")
    llm.add_argument("--llm", action="store_true", help="also ask a local LLM for context-aware absurd lines")
    llm.add_argument("--llm-backend", choices=("ollama", "claude"), default="ollama", help="which local model runner (default: ollama)")
    llm.add_argument("--llm-model", default="JOSIEFIED-Qwen3:8b", help="ollama model tag (ignored for claude backend)")
    llm.add_argument("--llm-count", type=int, default=40, help="how many lines to ask the LLM for (default: 40)")
    llm.add_argument("--llm-timeout", type=float, default=120.0, help="seconds to wait on the LLM (default: 120)")

    out = parser.add_argument_group("output")
    out.add_argument("--json", action="store_true", help="emit JSON objects (value, score, source) instead of plain lines")

    parser.add_argument("-v", "--verbose", action="store_true", help="print detailed progress to stderr")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress non-error output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _profile_from_args(args: argparse.Namespace) -> Profile:
    """Merge a loaded profile file (if any) with inline flags."""
    base = Profile()
    if args.profile:
        base = Profile.load(args.profile)
    inline = Profile.from_mapping(
        {
            "names": args.owner or [],
            "org": args.org or [],
            "framework": args.framework or [],
            "purpose": args.purpose or [],
            "keywords": args.keyword or [],
            "pets": args.pet or [],
            "dates": args.date or [],
            "extras": args.extra or [],
        }
    )
    return base.merge(inline)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        print(f"wd_gen: error: {exc}", file=sys.stderr)
        return 2

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    def vlog(message: str) -> None:
        if args.verbose and not args.quiet:
            print(message, file=sys.stderr)

    def warn(message: str) -> None:
        print(f"wd_gen: warning: {message}", file=sys.stderr)

    if args.list_rules:
        for name in RULES:
            marker = "*" if name in DEFAULT_RULES else " "
            print(f" {marker} {name}", file=sys.stderr)
        log("\n(* = enabled by default; select with --rules a,b,c)")
        return 0

    if args.rules:
        rules = tuple(r.strip() for r in args.rules.split(",") if r.strip())
        unknown = [r for r in rules if r not in RULES]
        if unknown:
            print(f"wd_gen: error: unknown rule(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
    else:
        rules = DEFAULT_RULES

    try:
        profile = _profile_from_args(args)
        wordlist = load_wordlist_file(args.wordlist) if args.wordlist else load_bundled_wordlist()
    except (ProfileError, WdGenError) as exc:
        print(f"wd_gen: error: {exc}", file=sys.stderr)
        return 1

    if profile.is_empty():
        warn("no profile facts given — output will be generic. Add --owner/--framework/... for pointed results")

    config = Config(
        profile=profile,
        wordlist=wordlist,
        rules=rules,
        count=args.count,
        mode="usernames" if args.usernames else "passwords",
        min_len=args.min_len,
        max_len=args.max_len,
        use_llm=args.llm,
        llm_backend=args.llm_backend,
        llm_model=args.llm_model,
        llm_count=args.llm_count,
        llm_timeout=args.llm_timeout,
    )

    rng = random.Random(args.seed)

    try:
        candidates = generate(config, rng, progress=vlog, warn=warn)
    except WdGenError as exc:
        print(f"wd_gen: error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(
            [{"value": c.value, "score": round(c.score, 2), "source": c.source} for c in candidates],
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        out = sys.stdout
        for c in candidates:
            out.write(c.value)
            out.write("\n")

    log(f"wd_gen: emitted {len(candidates)} {config.mode}")
    return 0

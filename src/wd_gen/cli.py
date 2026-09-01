"""Command-line interface for wd_gen.

Keeps stdout clean: only the generated usernames/passwords (or the JSON array)
go to stdout, one per line, so it pipes straight into a file or a tool that
consumes a wordlist. All progress, warnings, and errors go to stderr.

Exit codes: 0 success, 1 generation failed, 2 usage error / user aborted.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from . import __version__, planner
from .absurd import DEFAULT_OLLAMA_HOST
from .generate import (
    Config,
    WdGenError,
    generate,
    load_bundled_wordlist,
    load_wordlist_file,
)
from .mangle import DEFAULT_RULES, RULES
from .perms import DEFAULT_YEAR_RANGE
from .plan import BuildPlan, plan_to_dict
from .profile import Profile, ProfileError

_USERNAME_HINT = re.compile(r"\b(user ?names?|handles?|screen ?names?|nick(?:names?)?)\b", re.IGNORECASE)


class _UsageError(Exception):
    pass


def _default_llm_host() -> str:
    """$OLLAMA_HOST (normalised to a URL) if set, else the archserver default."""
    raw = os.environ.get("OLLAMA_HOST", "").strip()
    if not raw:
        return DEFAULT_OLLAMA_HOST
    return raw if "://" in raw else f"http://{raw}"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="wd_gen",
        description=(
            "Targeted OSINT/CTF credential wordlist generator. Give it a person's "
            "name and facts; it emits the plausible usernames and passwords that "
            "person would actually pick, ranked most-likely-first."
        ),
        epilog=(
            "For AUTHORIZED security testing / CTF / OSINT only. "
            "Example: wd_gen -u --owner 'Bogdan Stamenovix' --birthday 2001 --pet goose"
        ),
    )

    parser.add_argument("-n", "--count", type=int, default=5000,
                        help="how many candidates to emit (default: 5000)")
    parser.add_argument("-u", "--usernames", action="store_true",
                        help="generate usernames/handles instead of passwords")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="prompt for purpose + context (auto on a TTY with no target given)")
    parser.add_argument("--chaos", action="store_true",
                        help="absurd meme mode instead of realistic OSINT guesses")

    prof = parser.add_argument_group("target profile (give it everything you know)")
    prof.add_argument("--profile", metavar="FILE", help="load a profile file (JSON or simple 'field: a, b')")
    prof.add_argument("--owner", "--name", action="append", metavar="NAME",
                      dest="owner", help="target full name, e.g. 'Bogdan Stamenovix' (repeatable)")
    prof.add_argument("--nick", action="append", metavar="NICK", help="nickname/known handle (repeatable)")
    prof.add_argument("--org", action="append", metavar="ORG", help="employer/org (repeatable)")
    prof.add_argument("--framework", action="append", metavar="TECH", help="tech/interests (repeatable)")
    prof.add_argument("--purpose", action="append", metavar="TEXT", dest="purpose",
                      help="what the credential is FOR — 'office wifi', 'instagram login'. "
                           "Drives the plan (repeatable)")
    prof.add_argument("--context", metavar="TEXT", dest="brief",
                      help="free-text brief for the LLM planner: who the target is, the "
                           "situation, any facts — like writing an email")
    prof.add_argument("--keyword", action="append", metavar="WORD", help="city, hobby, job, anything (repeatable)")
    prof.add_argument("--pet", action="append", metavar="NAME", help="pet name (repeatable)")
    prof.add_argument("--birthday", "--date", action="append", metavar="D", dest="date",
                      help="birthday/year, e.g. 2001 or 23/05/2001 (repeatable)")
    prof.add_argument("--extra", action="append", metavar="WORD", help="partner, other trivia (repeatable)")

    gen = parser.add_argument_group("generation")
    gen.add_argument("--years", metavar="LO-HI", help=f"year range appended to names (default: {DEFAULT_YEAR_RANGE[0]}-{DEFAULT_YEAR_RANGE[1] - 1})")
    gen.add_argument("--no-common", action="store_true",
                     help="don't blend in generic common credentials (admin123, admin/root ...)")
    gen.add_argument("--common-weight", type=float, metavar="W",
                     help="force how heavily common creds rank: 0=suppress, ~1=interleave, "
                          "~1.6=top of list. Overrides context/LLM detection.")
    gen.add_argument("--min-len", type=int, default=3, help="drop candidates shorter than this (default: 3)")
    gen.add_argument("--max-len", type=int, default=48, help="drop candidates longer than this (default: 48)")
    gen.add_argument("--seed", type=int, help="RNG seed for reproducible output")
    gen.add_argument("--wordlist", metavar="FILE", help="custom base wordlist (chaos mode only)")
    gen.add_argument("--rules", metavar="LIST", help=f"chaos mangling rules (default: {','.join(DEFAULT_RULES)})")
    gen.add_argument("--list-rules", action="store_true", help="print chaos mangling rules and exit")

    llm = parser.add_argument_group("local LLM layer (optional, best-effort)")
    llm.add_argument("--llm", action="store_true", help="also ask a local LLM for context-aware candidates")
    llm.add_argument("--llm-backend", choices=("ollama", "claude"), default="ollama", help="model runner (default: ollama HTTP API)")
    llm.add_argument("--llm-model", default="goekdenizguelmez/JOSIEFIED-Qwen3:8b", help="ollama model tag (ignored for claude backend)")
    llm.add_argument("--llm-host", default=_default_llm_host(),
                     help=f"ollama server URL (default: $OLLAMA_HOST or {DEFAULT_OLLAMA_HOST})")
    llm.add_argument("--llm-count", type=int, default=40, help="how many lines to ask the LLM for (default: 40)")
    llm.add_argument("--llm-timeout", type=float, default=120.0, help="seconds to wait on the LLM (default: 120)")

    plan_grp = parser.add_argument_group("build plan (LLM planner)")
    plan_grp.add_argument("--plan", metavar="FILE", help="run a saved plan JSON instead of asking the planner")
    plan_grp.add_argument("--show-plan", action="store_true", help="print the build plan to stderr before generating")
    plan_grp.add_argument("--plan-only", action="store_true", help="print the build plan JSON to stdout and exit (no wordlist)")

    out = parser.add_argument_group("output")
    out.add_argument("--json", action="store_true", help="emit JSON objects (value, score, source) instead of plain lines")

    parser.add_argument("-v", "--verbose", action="store_true", help="detailed progress to stderr")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress non-error output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _profile_from_args(args: argparse.Namespace) -> Profile:
    base = Profile()
    if args.profile:
        base = Profile.load(args.profile)
    inline = Profile.from_mapping(
        {
            "names": (args.owner or []) + (args.nick or []),
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


def _infer_username_mode(*texts: str) -> bool:
    return any(_USERNAME_HINT.search(t or "") for t in texts)


def _prompt_brief() -> tuple[str, str]:
    """Interactive brief: one-line purpose, then a free-text context paragraph.

    Prompts go to stderr so stdout stays wordlist-only. Context ends on a blank
    line or EOF (Ctrl-D).
    """
    print("wd_gen: describe the target like you're writing a short email.", file=sys.stderr)
    print("purpose (what the credential is, e.g. 'office wifi password'):", file=sys.stderr)
    print("> ", end="", file=sys.stderr, flush=True)
    purpose = (sys.stdin.readline() or "").strip()
    print("context (who/where/facts; end with a blank line or Ctrl-D):", file=sys.stderr)
    print("> ", end="", file=sys.stderr, flush=True)
    lines: list[str] = []
    for line in sys.stdin:
        if not line.strip():
            break
        lines.append(line.rstrip("\n"))
    return purpose, " ".join(lines).strip()


def _load_plan(path: str) -> BuildPlan:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise WdGenError(f"cannot read plan {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WdGenError(f"invalid JSON in plan {path}: {exc}") from exc
    plan = BuildPlan.parse(data, source="file")
    if plan is None:
        raise WdGenError(f"plan {path}: top-level JSON must be an object")
    return plan


def _parse_years(spec: str | None) -> tuple[int, int]:
    if not spec:
        return DEFAULT_YEAR_RANGE
    m = spec.replace(":", "-").split("-")
    if len(m) != 2 or not all(p.strip().isdigit() for p in m):
        raise _UsageError(f"--years must be LO-HI, got {spec!r}")
    lo, hi = int(m[0]), int(m[1])
    if lo > hi:
        lo, hi = hi, lo
    return (lo, hi + 1)  # inclusive upper bound for the user


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        year_range = _parse_years(args.years)
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
        log("\n(* = enabled by default in --chaos mode; select with --rules a,b,c)")
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
        wordlist = (
            load_wordlist_file(args.wordlist)
            if args.wordlist
            else (load_bundled_wordlist() if args.chaos else [])
        )
    except (ProfileError, WdGenError) as exc:
        print(f"wd_gen: error: {exc}", file=sys.stderr)
        return 1

    style = "chaos" if args.chaos else "realistic"

    purpose = " ".join(args.purpose or []).strip()
    brief = (args.brief or "").strip()

    # Interactive brief: when asked, or on a TTY with nothing else to go on.
    want_interactive = style == "realistic" and not args.plan and (
        args.interactive
        or (
            sys.stdin.isatty() and profile.is_empty()
            and not purpose and not brief and not args.usernames
        )
    )
    if want_interactive:
        purpose, brief = _prompt_brief()

    # The short purpose is also a profile field, so the heuristic classifier and
    # token engine see it even without the LLM.
    if purpose:
        profile = profile.merge(Profile.from_mapping({"purpose": [purpose]}))

    mode = "usernames" if (args.usernames or _infer_username_mode(purpose, brief)) else "passwords"

    # Resolve the build plan (realistic only). Order: saved file > LLM planner
    # (when --llm / interactive / a brief is given) > None (generate builds the
    # heuristic plan itself, unless we need one to show).
    plan: BuildPlan | None = None
    if style == "realistic":
        try:
            if args.plan:
                plan = _load_plan(args.plan)
            elif args.llm or want_interactive or brief:
                plan = planner.llm_plan(
                    profile, purpose, brief, mode=mode,
                    backend=args.llm_backend, model=args.llm_model, host=args.llm_host,
                    timeout=args.llm_timeout, warn=warn, progress=vlog,
                )
            elif args.show_plan or args.plan_only:
                plan = planner.heuristic_plan(profile, mode=mode)
        except WdGenError as exc:
            print(f"wd_gen: error: {exc}", file=sys.stderr)
            return 1
        if plan is not None:
            mode = plan.mode

    if plan is not None and (args.show_plan or args.plan_only):
        rendered = json.dumps(plan_to_dict(plan), ensure_ascii=False, indent=2)
        if args.plan_only:
            print(rendered)
            log(f"wd_gen: plan only ({plan.source}); no wordlist generated")
            return 0
        print(rendered, file=sys.stderr)

    has_material = bool(plan and (plan.fragments or plan.fields)) or not profile.is_empty()
    if style == "realistic" and not has_material:
        warn("no target facts — give --owner/--birthday/..., a --context brief, or run interactively")

    config = Config(
        profile=profile,
        count=args.count,
        mode=mode,
        style=style,
        min_len=args.min_len,
        max_len=args.max_len,
        year_range=year_range,
        include_common=not args.no_common,
        common_weight=args.common_weight,
        plan=plan,
        wordlist=wordlist,
        rules=rules,
        use_llm=args.llm,
        llm_backend=args.llm_backend,
        llm_model=args.llm_model,
        llm_host=args.llm_host,
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

    log(f"wd_gen: emitted {len(candidates)} {style} {config.mode}")
    return 0

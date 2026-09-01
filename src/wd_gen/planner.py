"""The planner: natural-language brief -> a validated :class:`~wd_gen.plan.BuildPlan`.

Two producers, one output shape. :func:`llm_plan` asks the model to read the
free-text brief and *decide how the wordlist should be built* — extract the
fields, invent culturally-plausible name fragments, suggest topical seeds, choose
which engines and mangling rules to run (named built-ins and/or new ones it
authors), and set how heavily generic common credentials belong. :func:`heuristic_plan`
is the always-available fallback: no model, just the regex context classifier and
sensible defaults. Either way the executor in :mod:`generate` receives a
``BuildPlan`` and runs it deterministically.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from . import absurd, context, rules
from .plan import BuildPlan, ModuleSpec
from .profile import Profile

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?|```", re.IGNORECASE)


def _loads_lenient(text: str) -> object | None:
    """Extract and parse the JSON object from a model dump, repairing common
    small-model syntax slips (code fences, trailing commas, a stray quote wedged
    before a brace like ``},"{``). Returns the parsed object or ``None``."""
    text = _FENCE_RE.sub("", text)
    match = _JSON_RE.search(text)
    if not match:
        return None
    raw = match.group(0)
    for candidate in (raw, _repair(raw)):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _repair(s: str) -> str:
    s = re.sub(r'([\[,])\s*"\s*(\{)', r"\1\2", s)   # ,"{  ->  ,{   and  ["{  ->  [{
    s = re.sub(r'(\})\s*"\s*([,\]])', r"\1\2", s)   # }" ,  ->  } ,
    s = re.sub(r",(\s*[}\]])", r"\1", s)            # trailing commas before } or ]
    return s


def heuristic_plan(profile: Profile, *, mode: str) -> BuildPlan:
    """The no-LLM plan: context classifier for common weight, default rules."""
    is_username = mode == "usernames"
    policy = context.classify(profile, is_username=is_username)
    plan = BuildPlan(mode=mode, source="heuristic")
    plan.modules = {
        mode: ModuleSpec(enabled=True),
        "common": ModuleSpec(enabled=True, weight=policy.common_weight),
    }
    plan.rules = rules.default_rules()
    plan.common_weight = policy.common_weight
    plan.themed_seeds = list(policy.seeds)
    plan.notes = f"heuristic: {policy.note}"
    return plan


_PROMPT = """\
You are the planner for an AUTHORIZED CTF / security-audit wordlist generator.
You do NOT write passwords. You read the operator's brief and output a JSON PLAN
describing HOW a deterministic engine should build the {noun} wordlist. The engine
does the exhaustive permutation; you make the decisions it can't.

OPERATOR BRIEF
purpose: {purpose}
context: {context}

Decide, thinking about the NATURE of the target:
- Extract the useful facts into `fields` (first, last, pet, org, dates, keywords).
- Invent `fragments`: short culturally-plausible nickname/handle STEMS a real
  person would use, that can't be derived mechanically. E.g. Bogdan -> "bogi",
  "boki", "boba", "boda"; the engine will blend each with the surname (boda +
  Stamenovic -> "bodas"), so give stems, not full handles.
- `themed_seeds`: other words worth trying because they fit this person/context
  (a football club, a city, a game) — "this list could be relevant too".
- `modules`: enable engines and set weights. `common` folds in generic unrelated
  creds (admin123, password1, admin/root). Its `weight` is the key call:
  0 = suppress, ~1 = interleave, ~1.6 = put them on top.
  RULES OF THUMB: wifi key or admin/router login -> 1.5-1.7 (defaults dominate).
  A social-media USERNAME/handle is unique by nature, so generic handles are
  useless -> set `common_weight` 0 AND `modules.common.enabled` false.
  A password (any service) -> ~1.0 unless the context says otherwise.
- `rules`: pick mangling rules by name from AVAILABLE, and/or author new ones.
  AVAILABLE named rules: {rule_names}
  Authored rule shapes:
    {{"kind":"substitute","mapping":{{"a":"4","e":"3"}}}}
    {{"kind":"affix","append":["2024","!"],"prepend":["#"]}}
    {{"kind":"case","mode":"title"}}          (also: upper/lower/toggle/reverse)
    {{"kind":"regex","pattern":"(.+)","repl":"\\\\1_\\\\1"}}
- `common_weight`: 0.0-2.0, overall weight for the common creds (mirrors modules).

Output ONLY this JSON object, no prose, no code fence:
{{"mode":"{noun}","fields":{{"first":["..."],"last":["..."],"dates":["..."]}},
 "fragments":["..."],"themed_seeds":["..."],
 "modules":{{"{noun}":{{"enabled":true}},"common":{{"enabled":true,"weight":1.0}}}},
 "rules":[{{"kind":"named","name":"leet"}},{{"kind":"affix","append":["2024"]}}],
 "common_weight":1.0,"notes":"one line on your reasoning"}}
"""


def llm_plan(
    profile: Profile,
    purpose: str,
    brief: str,
    *,
    mode: str,
    backend: str,
    model: str,
    host: str,
    timeout: float,
    warn: Callable[[str], None],
    progress: Callable[[str], None] = lambda _m: None,
) -> BuildPlan:
    """Ask the model to plan the build; fall back to :func:`heuristic_plan`.

    Best-effort by contract: an unreachable host, a timeout, or output that won't
    parse all degrade to the heuristic plan so a run never fails on the LLM.
    """
    fallback = heuristic_plan(profile, mode=mode)
    prompt = _PROMPT.format(
        noun=mode,
        purpose=purpose or "(unspecified)",
        context=brief or "(none given)",
        rule_names=", ".join(rules.builtin_names()),
    )
    progress(f"planner: asking {model} @ {host}")
    text = absurd.llm_complete(prompt, backend=backend, model=model, host=host, timeout=timeout, warn=warn)
    data = _loads_lenient(text) if text is not None else None
    if data is None and text is not None:
        # One strict retry — small models often fix their own JSON when told.
        progress("planner: first plan unparseable, retrying with a strict reminder")
        retry = prompt + "\n\nYour previous reply was not valid JSON. Output ONLY the JSON object, no prose, no code fence, every array element comma-separated."
        text = absurd.llm_complete(retry, backend=backend, model=model, host=host, timeout=timeout, warn=warn)
        data = _loads_lenient(text) if text is not None else None
    if data is None:
        warn("planner: model gave no parseable plan; using heuristic plan")
        return fallback

    plan = BuildPlan.parse(data, source="llm")
    if plan is None:
        return fallback
    # The model may omit mode / a rule set; keep the run sane.
    plan.mode = mode
    if not plan.rules:
        plan.rules = rules.default_rules()
    if not plan.modules:
        plan.modules = fallback.modules
    return plan


def merged_profile(profile: Profile, plan: BuildPlan) -> Profile:
    """Fold the plan's extracted ``fields`` onto the CLI-supplied profile.

    The model emits fields as ``first``/``last``/``pet``/``dates``/…; those aren't
    canonical Profile keys, so we map them — crucially combining ``first`` +
    ``last`` into one two-word name entry, which is what lets the surname reach
    the fragment blender (``boda`` + Stamenovic -> ``bodas``).
    """
    f = plan.fields
    if not f:
        return profile

    def pick(*keys: str) -> list[str]:
        for k in keys:
            if f.get(k):
                return f[k]
        return []

    firsts = pick("first", "firstname", "first_name", "given")
    lasts = pick("last", "lastname", "last_name", "surname", "family")
    fulls = pick("name", "names", "fullname", "full_name")

    names = list(fulls)
    if firsts or lasts:
        combined = f"{firsts[0] if firsts else ''} {lasts[0] if lasts else ''}".strip()
        if combined:
            names.append(combined)
        names.extend(firsts[1:])
        names.extend(lasts[1:])

    mapping = {
        "names": names,
        "org": pick("org", "organization", "organisation", "company", "employer"),
        "pets": pick("pet", "pets", "animal"),
        "dates": pick("dates", "date", "dob", "birthday", "born", "year"),
        "keywords": pick("keywords", "keyword", "city", "town", "hobby", "hobbies", "interests"),
        "framework": pick("framework", "tech", "stack"),
        "extras": pick("extra", "extras", "partner", "spouse", "misc"),
    }
    return profile.merge(Profile.from_mapping(mapping))

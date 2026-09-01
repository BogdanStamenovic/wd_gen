"""The BuildPlan: the structured *decision* about how to build one wordlist.

This is the contract at the centre of wd_gen's LLM-as-planner design. The model
reads a natural-language brief and does not emit passwords — it emits a
``BuildPlan``: which tokens matter, which creative name fragments to try, which
permutation modules to run, which mangling rules to apply (named built-ins it
selected *and* new rules it authored), and how heavily to fold in generic common
credentials. The deterministic executor in ``generate`` then runs that plan.

Both paths produce a ``BuildPlan`` — the LLM planner and the heuristic fallback —
so the executor has exactly one input shape. Everything the model sends is
untrusted data: :func:`BuildPlan.parse` clamps numbers, drops malformed rules,
and **compile-checks every regex** so a bad pattern can never reach execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Ceilings so a runaway/confused model can never explode the run.
MAX_RULES = 40
MAX_FRAGMENTS = 60
MAX_SEEDS = 120
MAX_TOKEN_LEN = 64  # rules only ever apply to tokens this short (ReDoS bound)

# Rule kinds the executor understands. "named" references a built-in by name;
# the rest are authored inline by the model (or the heuristic planner).
RULE_KINDS = frozenset({"named", "substitute", "affix", "case", "regex"})
CASE_MODES = frozenset({"lower", "upper", "title", "capitalize", "toggle", "reverse"})


@dataclass
class RuleSpec:
    """One mangling rule: either a named built-in, or an authored transform.

    * ``named``      -> ``name`` picks a rule from ``rules.BUILTIN``.
    * ``substitute`` -> ``mapping`` char->char (leet: {"a":"4"}).
    * ``affix``      -> ``prepend`` / ``append`` string lists.
    * ``case``       -> ``mode`` in :data:`CASE_MODES`.
    * ``regex``      -> ``pattern`` / ``repl`` for ``re.sub`` (compile-checked).
    """

    kind: str
    label: str = ""
    name: str = ""
    mapping: dict[str, str] = field(default_factory=dict)
    prepend: list[str] = field(default_factory=list)
    append: list[str] = field(default_factory=list)
    mode: str = ""
    pattern: str = ""
    repl: str = ""
    _compiled: re.Pattern[str] | None = None

    @classmethod
    def parse(cls, data: Any) -> RuleSpec | None:
        """Validate one rule dict into a RuleSpec, or ``None`` if unusable."""
        if not isinstance(data, dict):
            return None
        kind = str(data.get("kind", "")).strip().lower()
        if kind not in RULE_KINDS:
            return None
        label = str(data.get("label") or data.get("name") or kind)[:40]

        if kind == "named":
            name = str(data.get("name", "")).strip()
            return cls(kind, label, name=name) if name else None

        if kind == "substitute":
            raw = data.get("mapping") or data.get("map") or {}
            if not isinstance(raw, dict):
                return None
            mapping = {
                str(k)[:1]: str(v)[:4]
                for k, v in raw.items()
                if str(k) and str(v) != ""
            }
            return cls(kind, label, mapping=mapping) if mapping else None

        if kind == "affix":
            pre = _str_list(data.get("prepend"))
            app = _str_list(data.get("append"))
            return cls(kind, label, prepend=pre, append=app) if (pre or app) else None

        if kind == "case":
            mode = str(data.get("mode", "")).strip().lower()
            return cls(kind, label, mode=mode) if mode in CASE_MODES else None

        # kind == "regex": compile now so a bad pattern never reaches execution.
        pattern = str(data.get("pattern", ""))
        if not pattern:
            return None
        try:
            compiled = re.compile(pattern)
        except re.error:
            return None
        return cls(kind, label, pattern=pattern, repl=str(data.get("repl", "")), _compiled=compiled)


def _str_list(value: Any, limit: int = 24) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s[:MAX_TOKEN_LEN])
        if len(out) >= limit:
            break
    return out


@dataclass
class ModuleSpec:
    """Whether an engine runs, and its weight/params."""

    enabled: bool = True
    weight: float = 1.0


@dataclass
class BuildPlan:
    """The full recipe for one wordlist. Produced by planner, run by executor."""

    mode: str = "passwords"  # "passwords" | "usernames"
    # Fields the planner extracted from the brief (merged onto any CLI profile).
    fields: dict[str, list[str]] = field(default_factory=dict)
    # Creative, culture-aware name/handle seeds the model invented (boda, bogi).
    fragments: list[str] = field(default_factory=list)
    # "This wordlist could be relevant too" — topical words (liverpool, anfield).
    themed_seeds: list[str] = field(default_factory=list)
    # Engine toggles: keys "usernames" | "passwords" | "common".
    modules: dict[str, ModuleSpec] = field(default_factory=dict)
    rules: list[RuleSpec] = field(default_factory=list)
    common_weight: float | None = None
    ranking: dict[str, float] = field(default_factory=dict)
    notes: str = ""
    source: str = "heuristic"  # "llm" | "heuristic"

    def module(self, name: str, default_enabled: bool = True) -> ModuleSpec:
        return self.modules.get(name, ModuleSpec(enabled=default_enabled))

    @classmethod
    def parse(cls, data: Any, *, source: str = "llm") -> BuildPlan | None:
        """Validate a raw plan dict (from the model) into a BuildPlan.

        Returns ``None`` only if ``data`` is not a dict at all; otherwise it
        salvages every usable field and drops the rest, so a partially-malformed
        plan still runs.
        """
        if not isinstance(data, dict):
            return None
        plan = cls(source=source)

        mode = str(data.get("mode", "")).strip().lower()
        if mode in ("passwords", "usernames"):
            plan.mode = mode

        fields_raw = data.get("fields")
        if isinstance(fields_raw, dict):
            plan.fields = {
                str(k).strip().lower(): _str_list(v, limit=40)
                for k, v in fields_raw.items()
                if _str_list(v)
            }

        plan.fragments = _str_list(data.get("fragments"), limit=MAX_FRAGMENTS)
        plan.themed_seeds = _str_list(data.get("themed_seeds") or data.get("themes"), limit=MAX_SEEDS)

        modules_raw = data.get("modules")
        if isinstance(modules_raw, dict):
            for key, spec in modules_raw.items():
                name = str(key).strip().lower()
                if name not in ("usernames", "passwords", "common"):
                    continue
                if isinstance(spec, bool):
                    plan.modules[name] = ModuleSpec(enabled=spec)
                elif isinstance(spec, dict):
                    plan.modules[name] = ModuleSpec(
                        enabled=bool(spec.get("enabled", True)),
                        weight=_clamp_float(spec.get("weight"), 1.0, 0.0, 2.0),
                    )

        rules_raw = data.get("rules")
        if isinstance(rules_raw, list):
            for item in rules_raw:
                spec = RuleSpec.parse(item)
                if spec is not None:
                    plan.rules.append(spec)
                if len(plan.rules) >= MAX_RULES:
                    break

        plan.common_weight = (
            _clamp_float(data["common_weight"], None, 0.0, 2.0)
            if "common_weight" in data
            else None
        )
        ranking_raw = data.get("ranking")
        if isinstance(ranking_raw, dict):
            plan.ranking = {
                str(k): _clamp_float(v, 0.0, -5.0, 5.0) for k, v in ranking_raw.items()
            }
        plan.notes = str(data.get("notes", ""))[:500]
        return plan


def rule_to_dict(spec: RuleSpec) -> dict[str, Any]:
    """Serialise one rule back to a plain dict (drops the compiled pattern)."""
    out: dict[str, Any] = {"kind": spec.kind, "label": spec.label}
    if spec.kind == "named":
        out["name"] = spec.name
    elif spec.kind == "substitute":
        out["mapping"] = spec.mapping
    elif spec.kind == "affix":
        out["prepend"], out["append"] = spec.prepend, spec.append
    elif spec.kind == "case":
        out["mode"] = spec.mode
    elif spec.kind == "regex":
        out["pattern"], out["repl"] = spec.pattern, spec.repl
    return out


def plan_to_dict(plan: BuildPlan) -> dict[str, Any]:
    """Serialise a BuildPlan to a JSON-ready dict (round-trips through parse)."""
    return {
        "mode": plan.mode,
        "source": plan.source,
        "fields": plan.fields,
        "fragments": plan.fragments,
        "themed_seeds": plan.themed_seeds,
        "modules": {
            name: {"enabled": m.enabled, "weight": m.weight}
            for name, m in plan.modules.items()
        },
        "rules": [rule_to_dict(r) for r in plan.rules],
        "common_weight": plan.common_weight,
        "ranking": plan.ranking,
        "notes": plan.notes,
    }


def _clamp_float(value: Any, default: float | None, lo: float, hi: float) -> Any:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(f, hi))

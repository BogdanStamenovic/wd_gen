"""Context-driven blending of *generic* common credentials into a targeted list.

A targeted profile alone only ever produces permutations of the target's own
name and facts. But real people often just pick ``admin123`` — a common password
with nothing to do with who they are. Whether that class *belongs* in the list,
and how high it should rank, depends entirely on **what the credential is for**:

  * a **WiFi key** or an **admin login** — common/default creds are extremely
    likely; float them near (or above) the targeted guesses.
  * an **Instagram username** — it is unique by nature; a generic ``admin`` is
    useless, so suppress the common class entirely and keep it personal.
  * anything unknown — a balanced interleave by real-world frequency.

That decision is a :class:`ContextPolicy`. It is produced two ways, mirroring the
rest of wd_gen's best-effort LLM contract:

  * :func:`classify` — deterministic regex/keyword rules over the profile's
    context fields. Always available; the floor.
  * :func:`llm_policy` — ask the bundled small LLM to read the free-text context
    and emit the policy as JSON. The intended primary path; falls back to
    :func:`classify` on any snag (missing binary, timeout, unparseable output).

:func:`common_credentials` and :func:`common_score` then supply and rank the
generic material the policy asked for.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files

from . import absurd
from .profile import Profile


@dataclass
class ContextPolicy:
    """How strongly, and how high, generic common credentials should blend in.

    ``common_weight`` scales both how *many* common creds are injected and how
    high they score (0.0 suppresses them entirely; ~1.0 interleaves by frequency;
    >1.4 lets the top common creds outrank the targeted guesses). ``common_bias``
    is a flat score offset on top of that. ``seeds`` are context-specific extra
    words worth trying (an SSID, a service name). ``note`` explains the call on
    stderr so the operator can see *why* the blend looks the way it does.
    """

    category: str = "generic"
    common_weight: float = 1.0
    common_bias: float = 0.0
    seeds: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def suppressed(self) -> bool:
        return self.common_weight <= 0.0


# --- category presets -------------------------------------------------------
#
# Keyed by (category, is_username). Usernames and passwords diverge sharply: an
# Instagram *username* is unique-by-nature (suppress generics) while an Instagram
# *password* is as reusable and guessable as any other (blend generics in).

_PRESETS: dict[tuple[str, bool], ContextPolicy] = {
    # Social handles: the username IS the identity — generic handles are useless.
    ("social", True): ContextPolicy("social", 0.0, note="social handle: unique by nature, common usernames suppressed"),
    ("social", False): ContextPolicy("social", 0.9, note="social password: reused/guessable, common passwords blended in"),
    # WiFi / router keys: defaults and simple keys dominate the real distribution.
    ("wifi", True): ContextPolicy("wifi", 0.6, note="wifi context: default device logins likely"),
    ("wifi", False): ContextPolicy("wifi", 1.6, seeds=["password", "12345678", "wifipassword", "internet"],
                                   note="wifi key: default/simple keys very likely, common creds ranked high"),
    # Admin panels / infra logins: default creds are the first thing anyone tries.
    ("admin", True): ContextPolicy("admin", 1.7, note="admin login: default handles (admin/root) ranked high"),
    ("admin", False): ContextPolicy("admin", 1.6, seeds=["admin", "password", "changeme", "default"],
                                    note="admin login: default/common passwords ranked high"),
    # Corporate SSO / email: complexity policy + company words; a measured blend.
    ("corporate", True): ContextPolicy("corporate", 0.7, note="corporate account: some default handles, mostly identity-derived"),
    ("corporate", False): ContextPolicy("corporate", 0.9, note="corporate account: policy-shaped 'Word2024!' plus common creds"),
    # Nothing recognisable: balanced interleave by frequency (the sane default).
    ("generic", True): ContextPolicy("generic", 0.8, note="no specific context: balanced common-handle interleave"),
    ("generic", False): ContextPolicy("generic", 1.0, note="no specific context: balanced common-password interleave"),
}

# Regex signals per category, matched against the profile's free-text context.
# Ordered by priority: on a tie in signal count, the earlier category wins (a
# "router admin login" scores admin=2, wifi=1 -> admin; "office wifi" scores
# wifi=1, corporate=1 -> ... wifi loses the tiebreak to corporate below it, so
# wifi is placed above corporate here where the login-vs-key intent is clearer).
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("admin", re.compile(
        r"\b(admin|administrator|root|login\s*page|dashboard|panel|cpanel|phpmyadmin|"
        r"ssh|telnet|ftp|rdp|database|mysql|postgres|oracle|redis|jenkins|gitlab|"
        r"grafana|kibana|appliance|firewall|\bnas\b|iot|camera|cctv|dvr|default\s*cred)\b",
        re.IGNORECASE)),
    ("wifi", re.compile(
        r"\b(wifi|wi-fi|wlan|wpa|wpa2|wpa3|psk|ssid|router|hotspot|access\s*point|"
        r"modem|broadband|network\s*key)\b", re.IGNORECASE)),
    ("social", re.compile(
        r"\b(instagram|insta|\big\b|twitter|tweet|tiktok|snapchat|snap|facebook|"
        r"\bfb\b|reddit|discord|telegram|whatsapp|onlyfans|social|handle|gamertag|"
        r"steam|twitch|youtube|forum)\b", re.IGNORECASE)),
    ("corporate", re.compile(
        r"\b(corporate|company|enterprise|business|office|o365|office365|outlook|"
        r"exchange|ldap|active\s*directory|azure|okta|\bvpn\b|\bsso\b|intranet|"
        r"workday|sharepoint|email|webmail|payroll)\b", re.IGNORECASE)),
)


def _context_text(profile: Profile) -> str:
    """The free-text fields that describe what the credential is FOR."""
    parts: list[str] = []
    for name in ("purpose", "framework", "org", "keywords"):
        parts.extend(getattr(profile, name))
    return " ".join(parts)


def classify(profile: Profile, *, is_username: bool) -> ContextPolicy:
    """Regex/keyword classification of the context into a common-cred policy.

    Deterministic and always available — the floor under :func:`llm_policy`.
    """
    text = _context_text(profile)
    best_category = "generic"
    best_count = 0
    for category, pattern in _CATEGORY_PATTERNS:
        count = len(pattern.findall(text))
        if count > best_count:  # strict > keeps the higher-priority category on ties
            best_count = count
            best_category = category
    return _PRESETS[(best_category, is_username)]


# --- LLM policy -------------------------------------------------------------

_POLICY_PROMPT = """\
You are tuning a targeted credential-guessing wordlist for an AUTHORIZED CTF / \
security audit. Decide how much WEIGHT to give GENERIC common credentials \
(like {examples}) versus credentials derived from the specific target's own \
name and facts.

The wordlist is for this {noun} context:
{context}

Think about the NATURE of that context:
- A social-media USERNAME is unique by its nature, so generic handles are \
useless -> weight near 0.
- A WiFi key or an admin/router login is very often a default or common value \
-> high weight.
- A corporate account has a complexity policy -> moderate weight.
- If unsure, use a balanced 1.0.

Reply with ONE line of JSON and nothing else:
{{"category": "<social|wifi|admin|corporate|generic>", "common_weight": <0.0-2.0>, \
"seeds": ["<optional context-specific words to also try>"], "note": "<short why>"}}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def llm_policy(
    profile: Profile,
    *,
    is_username: bool,
    backend: str,
    model: str,
    host: str = absurd.DEFAULT_OLLAMA_HOST,
    timeout: float,
    warn: Callable[[str], None],
) -> ContextPolicy:
    """Ask the small LLM to read the context and set the common-cred policy.

    Falls back to :func:`classify` on any failure — missing binary, timeout, or
    output we cannot parse into a sane policy — so the caller always gets a usable
    policy. This is the path ownbox's bundled model is meant to take.
    """
    fallback = classify(profile, is_username=is_username)
    context = _context_text(profile).strip() or "(no context given)"
    noun = "username" if is_username else "password"
    examples = "admin, root, test, guest" if is_username else "admin123, password1, 123456"
    prompt = _POLICY_PROMPT.format(examples=examples, noun=noun, context=context)

    text = absurd.llm_complete(
        prompt, backend=backend, model=model, host=host, timeout=timeout, warn=warn
    )
    if text is None:
        return fallback

    match = _JSON_RE.search(text)
    if not match:
        warn("llm: policy response had no JSON; using regex classification")
        return fallback
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        warn("llm: policy JSON did not parse; using regex classification")
        return fallback
    if not isinstance(data, dict):
        return fallback

    try:
        weight = float(data.get("common_weight", fallback.common_weight))
    except (TypeError, ValueError):
        weight = fallback.common_weight
    weight = max(0.0, min(weight, 2.0))  # clamp: no runaway ranking

    seeds_raw = data.get("seeds") or []
    seeds = [str(s).strip() for s in seeds_raw if isinstance(s, (str, int, float)) and str(s).strip()][:12]

    category = str(data.get("category") or fallback.category)
    note = str(data.get("note") or "").strip() or f"llm policy ({category})"
    return ContextPolicy(category=category, common_weight=weight,
                         common_bias=fallback.common_bias, seeds=seeds,
                         note=f"llm: {note}")


# --- common credential source + scoring -------------------------------------


def _load(name: str) -> list[str]:
    text = files("wd_gen.data").joinpath(name).read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        w = line.strip()
        if w and not w.startswith("#"):
            out.append(w)
    return out


def load_common_passwords() -> list[str]:
    """Frequency-ordered common passwords (most common first)."""
    return _load("common_passwords.txt")


def load_common_usernames() -> list[str]:
    """Frequency-ordered common/default usernames (most common first)."""
    return _load("common_usernames.txt")


def common_credentials(*, is_username: bool) -> list[str]:
    return load_common_usernames() if is_username else load_common_passwords()


def common_score(rank: int, total: int, policy: ContextPolicy) -> float:
    """Score a common credential at frequency ``rank`` (0 = most common).

    Lives in the same band as :func:`wd_gen.perms.plausibility` so the two sources
    interleave sensibly. With ``common_weight`` ~1.0 the very top common creds
    land around the targeted guesses (~7) and the long tail sinks toward the
    bottom; with a high weight (wifi/admin) the top can overtake the targeted
    guesses, and with weight 0 the source is suppressed upstream.
    """
    if total <= 0:
        return 0.0
    freq = 1.0 - (rank / total)  # 1.0 for the most common, ->0 for the rarest
    return policy.common_bias + policy.common_weight * (2.0 + 5.0 * freq)

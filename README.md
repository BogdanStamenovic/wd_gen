# wd_gen

Targeted OSINT/CTF credential wordlist generator with a small LLM as the
**planner**. You describe the target and the situation in plain language; the LLM
decides *how* the list should be built — which facts matter, which nickname
stems to try, which mangling rules to run (and it can write new ones), how
heavily to fold in generic common passwords — and a deterministic engine executes
that plan. The model decides; the engine makes.

This is the [CUPP](https://github.com/Mebus/cupp) +
[username-anarchy](https://github.com/urbanadventurer/username-anarchy) lineage
with an orchestration layer on top: credential *profiling*, not random tumbling.

```
$ wd_gen
purpose (what the credential is, e.g. 'office wifi password'):
> instagram username
context (who/where/facts; end with a blank line or Ctrl-D):
> Target is Bogdan Stamenovic, goes by Bogi sometimes, born 2001.
> I want his likely instagram handle.

→ bogi, bogis, boba, bobas, bogdanstam, bogi2001, stamenovic01, b0gis, ...
```

The model reads that brief, extracts the fields, and invents the
culturally-plausible stems an algorithm can't — *Bogdan → bogi, boki, boba,
boda* — which the engine then blends with the surname (`boda` + **S**tamenovic →
`bodas`). It also decided this is a *handle*, which is unique by nature, so it
**suppressed** the generic `admin`/`root` class entirely. Point it at a WiFi key
or an admin login instead and it does the opposite — defaults like `admin123`
lead the list.

> **Authorized use only.** This is a tool for CTF challenges, OSINT exercises,
> and password audits you are permitted to run. It generates a wordlist and
> writes it to stdout — it does no hashing, cracking, spraying, or network I/O
> beyond talking to your own LLM server. What you point it at is your responsibility.

## How it works

**The planner → executor split.** Every realistic run is driven by a *build
plan*. The LLM planner produces it from your brief; when no LLM is reachable a
regex classifier produces a heuristic one instead. Either way the executor gets
the same structure and runs it deterministically (reproducible under `--seed`).
See the plan for any run with `--show-plan`, save/edit/replay it with
`--plan-only` / `--plan FILE`.

The plan decides:

- **fields** — the name/pet/org/dates pulled out of your free-text context.
- **fragments** — creative nickname stems the model invents (`bogi`, `boda`),
  which the engine blends with the surname into handles (`bodas`, `bogistam`).
- **themed_seeds** — "this list could be relevant too" material (a football
  club, a city, a game).
- **modules** — which engines run (usernames / passwords / common).
- **rules** — mangling rules, chosen from the built-in set **and authored on the
  spot**: `substitute` (leet maps), `affix` (prepend/append), `case`, and raw
  `regex` (`{pattern, repl}`). Authored regex is compile-checked and sandboxed to
  short tokens, so a bad rule can't crash or hang the run.
- **common_weight** — how heavily to fold in the generic common credentials
  (`admin123`, `password1`, `admin`/`root`) that a targeted list never covers on
  its own. Its value is a judgement about the credential's *nature*:

| Context | Common creds |
| --- | --- |
| `office wifi` / `router admin login` | ranked **at the top** — defaults dominate here |
| a password, unknown service | **interleaved** by real-world frequency |
| `instagram username` | **suppressed** — a handle is unique, a generic one is useless |

The permutation engine underneath is comprehensive: first/last/f.last/initials,
truncations, the fragment blender, birthday expansion (YYYY/YY/DDMM/DDMMYYYY),
name+name combos, casings, light leet, policy shapes (`Word2024!`). Results are
ranked most-likely-first by a plausibility heuristic — the target's own material
and real dates outrank generic years; for usernames, everything is forced
url-safe so a symbol rule can't leak an invalid handle.

**The LLM** (`--llm`, and on automatically for an interactive/`--context` run)
talks to an **ollama server over HTTP** — default `http://archserver:11434`,
overridable with `--llm-host` or `$OLLAMA_HOST`, so no local model or `ollama`
binary is needed. `--llm-backend claude` swaps in a keyless `claude -p`. It is
strictly best-effort: an unreachable host, a cold model, a timeout, or
unparseable JSON (with one repair-and-retry) all fall back to the heuristic plan
with a warning — a run never fails on the LLM.

You can still skip the planner entirely and drive it with flags
(`--owner`/`--birthday`/…); that path uses the heuristic plan. Force the common
weight yourself with `--common-weight` (`0` suppresses, `~1` interleaves, `~1.6`
tops the list) or kill the class with `--no-common`.

**Chaos (`--chaos`)** — the absurd meme generator (themed word banks + rule
mangling): `MoistHamsterOverlord69!`. Memorable, not realistic. It was the
original ask, kept behind the flag.

Both are deterministic under `--seed`; the optional LLM layer is not.

## Install

Via [ownbox](https://github.com/BogdanStamenovic/ownbox): `ownbox install wd_gen`
from the repo root (`ownbox.yaml` is included).

Manual (editable venv):

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/wd_gen --version
```

## Usage

```sh
wd_gen [options] > wordlist.txt
```

| Option | Meaning |
| --- | --- |
| *(bare `wd_gen` on a TTY)* | prompts for **purpose** then **context** and lets the LLM plan |
| `-i, --interactive` | force the interactive brief (even when flags are given) |
| `-n, --count N` | how many candidates to emit (default 5000) |
| `-u, --usernames` | generate handles instead of passwords |
| `--chaos` | absurd meme mode instead of realistic OSINT |
| `--profile FILE` | load a target profile (JSON or `field: a, b` lines) |
| `--owner "First Last"` | target's full name (repeatable) |
| `--nick` | known nickname/handle (repeatable) |
| `--purpose TEXT` | what the credential is (`office wifi password`, `instagram username`) |
| `--context TEXT` | free-text brief for the planner — who/where/facts, like an email |
| `--birthday D` | birthday/year — `2001` or `23/05/2001` (repeatable) |
| `--org / --pet / --keyword / --extra` | employer, pet, city/hobby/job, partner… |
| `--no-common` | don't blend in generic common credentials |
| `--common-weight W` | force the common-cred weight: `0` suppress, `~1` interleave, `~1.6` top of list |
| `--llm` | use the LLM planner (auto-on for an interactive or `--context` run) |
| `--llm-host URL` | ollama server URL (default `$OLLAMA_HOST` or `http://archserver:11434`) |
| `--llm-backend / --llm-model` | `ollama\|claude`, and the ollama model tag |
| `--plan FILE` | run a saved plan JSON instead of asking the planner |
| `--show-plan` | print the build plan to stderr before generating |
| `--plan-only` | print the plan JSON to stdout and exit (no wordlist) |
| `--years LO-HI` | year range appended to names (default 1970–2026) |
| `--min-len / --max-len` | length window (default 3–48) |
| `--seed N` | reproducible RNG |
| `--json` | emit `{value, score, source}` objects instead of plain lines |
| `-v/-q` | verbose / quiet (both to stderr) |

stdout carries only the wordlist (or the JSON array); prompts, progress, warnings
and errors go to stderr. Exit codes: `0` ok, `1` failed, `2` usage error.

### Examples

```sh
# interactive: it asks for purpose, then a free-text context, then plans the build
wd_gen > wordlist.txt

# same, non-interactively: purpose + an email-style brief, LLM plans it
wd_gen --purpose "office wifi password" \
       --context "Auditing the home router. Owner Bogdan Stamenovic, born 2001,
                  pet goose Gilbert, big Liverpool fan. Need the WPA2 key." > wifi.txt

# see the plan the model produced, without generating a wordlist
wd_gen --purpose "instagram username" --context "Bogdan, aka Bogi, born 2001" --plan-only

# save a plan, tweak it, replay it deterministically
wd_gen --purpose "..." --context "..." --plan-only > plan.json
wd_gen --plan plan.json --seed 1 -n 5000 > wordlist.txt

# no LLM / no brief: classic flag-driven run (heuristic plan)
wd_gen -u --owner "Bogdan Stamenovic" --birthday 2001 --pet goose --seed 1

# force the common-cred weight yourself, skip the planner's judgement
wd_gen --owner "Bogdan Stamenovic" --common-weight 1.6 -n 5000

# reproducible JSON with plausibility scores and provenance
wd_gen --owner "Ada Lovelace" --birthday 1815 --seed 42 --json -n 100

# the original absurd mode, still here
wd_gen --chaos --owner Bogdan --pet goose -n 3000
```

A profile file is either JSON:

```json
{ "owner": ["Bogdan Stamenovix"], "birthday": ["23/05/2001"], "pet": ["goose"],
  "keywords": "pigion, belgrade", "org": ["Acme"] }
```

or the simpler line format:

```
owner: Bogdan Stamenovix
birthday: 23/05/2001
pet: goose
keywords: pigion, belgrade
```

## Limitations

- **It generates lines. That's all.** No hashing, cracking, credential testing,
  or spraying; the only network I/O is talking to your own LLM server. Feed the
  output to a tool you're authorized to run.
- **The planner is only as good as the small model.** It decides fields,
  fragments, rules and weights — an 8B model gets this mostly right but not
  always (it may under- or over-weight the common class, or miss a nickname).
  Use `--show-plan` to see the call and `--common-weight` / `--plan FILE` to
  override it.
- **Plausibility is a heuristic, not a guarantee.** It orders guesses by how
  commonly real people pick each shape — it can't know your specific target's
  quirks.
- **The LLM layer is best-effort.** If the ollama host is unreachable, the model
  is cold, it times out, or its JSON won't parse (after one repair-and-retry),
  wd_gen warns on stderr and the heuristic plan covers the run.
- **Realistic mode is best with a target.** With an empty profile the targeted
  engine has nothing to build from, so you get only the generic common-credential
  list (a useful standalone wordlist, but not *targeted*) — add `--no-common` and
  it emits nothing with a warning. Give it a name and facts for the real value.
- **Dedup can fall short of `--count`** for a thin profile; it emits what it has
  and says so. Widen the profile or the `--years` range for more.

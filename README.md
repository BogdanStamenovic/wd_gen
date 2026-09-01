# wd_gen

Targeted OSINT/CTF credential wordlist generator. Give it a person's name and
whatever facts you have; it emits the *plausible* usernames and passwords that
specific person would actually pick — ranked most-likely-first, so the best
guesses are at the top of the file.

This is the [CUPP](https://github.com/Mebus/cupp) +
[username-anarchy](https://github.com/urbanadventurer/username-anarchy) lineage:
credential *profiling*, not random tumbling. For a target named
**Bogdan Stamenovix, born 2001, pet goose** it produces the systematic space a
real person picks from —

```
bogdans          bstamenovix      bogdan.stamenovix    bogdanstamenovix
Bogdan2001       Bogdan123        Pigion2001           Bogdan230501   (DDMMYY)
b0gdan           goosebogdan      Bogdan2001!          bstamen
```

— plus the **generic common credentials** a person picks regardless of who they
are (`admin123`, `password1`, `123456`, and for handles `admin`/`root`), blended
in and ranked by how much they fit the context — plus, optionally, a small local
LLM to cover the non-systematic handles a person invents (`bogdanthegeese2001`,
`stam3novix2001`).

> **Authorized use only.** This is a tool for CTF challenges, OSINT exercises,
> and password audits you are permitted to run. It generates a wordlist and
> writes it to stdout — it does no hashing, cracking, spraying, or network I/O
> of any kind. What you point it at is your responsibility.

## How it works

Two engines, picked by a flag:

**Realistic (default)** — enumerates the shapes people demonstrably choose from
the target's own tokens:

```
usernames: first, last, first+last, f.last, first+lastinitial, initials,
           truncations, nick, token+year, light leetspeak
passwords: token + meaningful year/number (birthday expands to YYYY/YY/DDMM/
           DDMMYYYY), + one symbol, name+name combos, Title/UPPER/leet casings
```

Ranked by a *plausibility* heuristic: the target's own name and **real** dates
outrank generic years, plain handles stay near the top, symbol-soup sinks.

**Common credentials, weighted by context** — a targeted list alone never
contains `admin123`, but real people use it. So wd_gen also blends in a
frequency-ranked list of the passwords/handles people pick *regardless of
identity*. How high they rank — or whether they belong at all — is decided by
**what the credential is for**, because that is in its nature:

| Context (`--context`) | Common creds |
| --- | --- |
| `office wifi` / `router admin login` | ranked **at the top** — defaults dominate here |
| *(nothing / unknown)* | **interleaved** by real-world frequency |
| `instagram username` | **suppressed** — a handle is unique, a generic one is useless |

The small LLM reads the free-text context and sets that weight; when it's absent
a regex classifier does the same job (`wifi`/`admin`/`social`/`corporate`/
`generic`). Force it yourself with `--common-weight` (`0` suppresses, `~1`
interleaves, `~1.6` tops the list), or turn the whole class off with
`--no-common`.

The LLM (`--llm`) talks to an **ollama server over HTTP** — by default
`http://archserver:11434`, overridable with `--llm-host` or `$OLLAMA_HOST`, so no
local model or `ollama` binary is needed. It's used for two things: setting the
context/common-cred policy above, and generating the non-systematic creative
handles. `--llm-backend claude` swaps in a keyless `claude -p` instead. Either
way it's strictly additive: unreachable host, cold model, or timeout just drops
the layer with a warning and the deterministic engine covers the run.

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
| `-n, --count N` | how many candidates to emit (default 5000) |
| `-u, --usernames` | generate handles instead of passwords |
| `--chaos` | absurd meme mode instead of realistic OSINT |
| `--profile FILE` | load a target profile (JSON or `field: a, b` lines) |
| `--owner "First Last"` | target's full name (repeatable) |
| `--nick` | known nickname/handle (repeatable) |
| `--context TEXT` | what the credential is *for* (`office wifi`, `instagram login`) — drives the common-cred blend (repeatable; alias `--purpose`) |
| `--birthday D` | birthday/year — `2001` or `23/05/2001` (repeatable) |
| `--org / --pet / --keyword / --extra` | employer, pet, city/hobby/job, partner… |
| `--no-common` | don't blend in generic common credentials |
| `--common-weight W` | force the common-cred weight: `0` suppress, `~1` interleave, `~1.6` top of list |
| `--years LO-HI` | year range appended to names (default 1970–2026) |
| `--min-len / --max-len` | length window (default 3–48) |
| `--seed N` | reproducible RNG |
| `--llm` | also ask an LLM (`--llm-backend ollama\|claude`, `--llm-model`) |
| `--llm-host URL` | ollama server URL (default `$OLLAMA_HOST` or `http://archserver:11434`) |
| `--json` | emit `{value, score, source}` objects instead of plain lines |
| `-v/-q` | verbose / quiet (both to stderr) |

stdout carries only the wordlist (or the JSON array); progress, warnings and
errors go to stderr. Exit codes: `0` ok, `1` failed, `2` usage error.

### Examples

```sh
# usernames for a target, birthday-aware ranking
wd_gen -u --owner "Bogdan Stamenovix" --birthday 2001 --pet goose --seed 1

# passwords, full date expands to DDMM / DDMMYY / DDMMYYYY tails
wd_gen --owner "Bogdan Stamenovix" --birthday 23/05/2001 --org Acme -n 5000

# context decides the blend: a wifi key -> common creds rank at the top
wd_gen --owner "Bogdan Stamenovix" --context "home wifi wpa2 key" -n 5000

# an admin login -> admin/root/default creds lead; --llm lets the model judge
wd_gen -u --owner "Bogdan Stamenovix" --context "router admin login page" --llm

# an instagram handle is unique by nature -> generic handles suppressed
wd_gen -u --owner "Bogdan Stamenovix" --context "instagram username"

# add local-LLM coverage for the creative handles, keep 8–16 char results
wd_gen -u --profile target.profile --llm --min-len 8 --max-len 16

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
  or network I/O. Feed the output to a tool you're authorized to run.
- **Plausibility is a heuristic, not a guarantee.** It orders guesses by how
  commonly real people pick each shape — it can't know your specific target's
  quirks. Truly random handles (`b0g13a`) are where the `--llm` layer helps and
  even then it's guessing.
- **The LLM layer is best-effort.** If the ollama host is unreachable, the model
  is cold, or it times out, wd_gen warns on stderr and the deterministic engine
  covers the count on its own.
- **Realistic mode is best with a target.** With an empty profile the targeted
  engine has nothing to build from, so you get only the generic common-credential
  list (a useful standalone wordlist, but not *targeted*) — add `--no-common` and
  it emits nothing with a warning. Give it a name and facts for the real value.
- **Dedup can fall short of `--count`** for a thin profile; it emits what it has
  and says so. Widen the profile or the `--years` range for more.

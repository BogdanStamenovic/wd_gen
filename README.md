# wd_gen

Generate absurd, memorable passwords and usernames from a target profile.

You give it the most info you can — who the owner is, what the framework is,
what the thing is *for*, plus whatever trivia you've got — and it turns a
generic base wordlist into a large pile (5000+ by default) of candidates. Half
of them are ordinary hashcat-style manglings; the other half are unhinged
passphrases that read like a Discord handle achieved sentience:
`MoistHamsterOverlord69!`, `BogdanNextJs_deadass`, `ForbiddenGuacamoleBaron1337`.
The point is the "are we for real bro" quality.

It is **not** a cracker and it does not hash, test, or spray anything. It writes
lines to stdout. What you do with the list is your business — the intended use
is generating memorable credentials for your own accounts and seeding your own
password manager, or building a themed candidate set for authorized testing.

## How it works

```
seeds  = profile tokens  (+ pairwise profile combos, high-signal)
       + bundled/base wordlist
raw    = mangle(seed, rules)          leet, case, number/symbol/meme tails, "bro"-isms
       + absurd template passphrases  themed word banks, topped up to hit the count
       + local-LLM lines              optional, context-aware, best-effort
shaped = raw                          in password mode
       | to_usernames(raw)            in username mode  (no spaces, url-safe)
result = dedup, scored by absurdity/memorability, sorted, capped at --count
```

Everything runs off a single seeded RNG, so `--seed N` reproduces a run exactly
(the optional LLM layer aside — that's inherently non-deterministic).

## Install

Via [ownbox](https://github.com/BogdanStamenovic/ownbox):

```yaml
# ownbox.yaml is included; `ownbox install wd_gen` from the repo root
```

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
| `-u, --usernames` | generate handles instead of passwords (no spaces, url-safe) |
| `--profile FILE` | load a profile (JSON, or simple `field: a, b` lines) |
| `--owner / --org / --framework / --purpose` | profile facts (repeatable, comma-ok) |
| `--keyword / --pet / --date / --extra` | more profile facts (repeatable) |
| `--wordlist FILE` | custom base wordlist instead of the bundled one |
| `--rules a,b,c` | pick mangling rules (`--list-rules` to see them) |
| `--min-len / --max-len` | length window (default 4–48) |
| `--seed N` | reproducible RNG |
| `--llm` | also ask a local LLM for context-aware lines |
| `--llm-backend ollama\|claude` | which local runner (default ollama) |
| `--llm-model TAG` | ollama model tag |
| `--json` | emit `{value, score, source}` objects instead of plain lines |
| `-v/-q` | verbose / quiet (both go to stderr) |

stdout carries only the output (lines, or the JSON array), so it pipes cleanly.
Progress, warnings and errors all go to stderr. Exit codes: `0` ok, `1` failed,
`2` usage error.

### Examples

```sh
# 5000 absurd passwords pointed at a specific target
wd_gen --owner "Bogdan Stamenovic" --org Pigion --framework Next.js \
       --purpose "self-running infrastructure" --keyword archserver --seed 1

# usernames instead
wd_gen --usernames --owner Bogdan --framework Rust -n 2000

# load facts from a file, add local-LLM flavour, keep only 12–24 char results
wd_gen --profile target.profile --llm --min-len 12 --max-len 24

# reproducible JSON with scores and provenance
wd_gen --owner Ada --seed 42 --json -n 100
```

A profile file is either JSON:

```json
{ "owner": ["Bogdan"], "framework": ["Next.js", "FastAPI"], "keywords": "pigion, archserver" }
```

or the simpler line format:

```
owner: Bogdan Stamenovic
framework: Next.js, FastAPI
keywords: pigion, archserver
```

## Limitations

- **Not a security tool in the offensive sense.** It generates lines. It does
  no hashing, cracking, credential testing, or network I/O of any kind.
- **The LLM layer is best-effort.** If `ollama`/`claude` is missing, cold, or
  times out, wd_gen warns on stderr and falls back to the deterministic template
  floor — the requested count is always met without it.
- **Absurdity/memorability scoring is a heuristic**, not a strength estimate.
  A high score means "more unhinged and more memorable", not "harder to crack".
  These are memorable by design, which is the opposite of high-entropy random.
- **Dedup can saturate** a narrow request (tiny profile + tight length window +
  few rules). When it can't reach `--count` it emits what it has and says so.

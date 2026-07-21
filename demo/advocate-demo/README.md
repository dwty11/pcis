# The Advocate Demo

A legal-assistant agent's knowledge tree holds ~18 ordinary case-file claims — filing
deadlines, real statute references, procedural notes, client facts — and **one plant**:
a well-formatted, entirely fabricated case citation, held at **0.95 confidence** with no
source. It is indistinguishable from the real precedents beside it at a glance. That is
the documented failure mode: the advocate who was sanctioned did not miss a garbled
citation — he trusted a perfectly-formatted one.

On a maintenance pass the gardener reads the tree together with recent session memory and
challenges its highest-confidence claims. **It is never told which leaf to attack.** Its
strongest counter lands on the fabricated citation, grounded in the record's own
verification note — a session log recording that the case returned no results in Westlaw.

## What it honestly claims

PCIS **did not** prove the ruling doesn't exist — an offline model can't, and the case
citation could be real for all the model knows. What it did: a high-confidence claim with
no source was **challenged against the record's own verification note**, its confidence
**moved under challenge** (net 0.95 → mid-0.80s), and the challenge is now **permanently on
the record, surfaced for a human's review.** The claim did not "fail" and it did not flip —
it moved, and the record grew. The court says verification is the professional's duty; the
demo makes that duty **structural**.

> "PCIS catches hallucinated citations" would be a lie. This is the true claim, and it is
> the stronger one.

## Run it

```bash
cd demo/advocate-demo

./run_demo.sh                 # default: replay a locked, recorded REAL gardener run
./run_demo.sh --live          # run the shipped gardener fresh on your own local model
./run_demo.sh --verify-self   # SHA-256 every script + fixture vs CANONICAL_FINGERPRINT.txt
```

- **`--replay` (default)** needs nothing but Python stdlib and the shipped fixtures — no
  network, no model, no key, `<60s` on any machine. It replays a recorded real run and
  labels itself as a replay, with the model and timestamp on screen.
- **`--live`** runs the shipped `core/gardener.py` — the same code, the same prompt, no leaf
  id, no hint — against the same seeded tree on your own Ollama model. Counters vary run to
  run; that's disclosed on screen.

**Everything runs on your machine. Nothing leaves it.** The public gardener is Ollama/MLX
only — there is no cloud path in `core/gardener.py` — and replay needs no model at all.

## How it stays honest

- **The gardener is not told the target.** `run_demo.sh` and `record_canonical.py` build the
  shipped `GARDENER_PROMPT` with no leaf id and no hint — grep them. The seeded tree ships in
  full (`fixtures/seed_tree.json`); read all 18 leaves and judge whether the plant is unfairly
  obvious.
- **The quota is disclosed, not hidden.** The shipped prompt asks for 3–5 counters, so "it
  attacked something" is guaranteed. The demo shows **every** counter it raised, weak and
  wrong ones included, and which one bit. The claim is not "PCIS only attacks wrong beliefs" —
  it's "challenges become part of the record, the biting one moves the belief, and a human
  reviews."
- **The hit-rate is a measured number, not an adjective.** Across the shipped 10-pass
  recording (`fixtures/hit_rate.json`, model `qwen3.5:9b`), the gardener landed a counter on
  the plant in **6 of 10** runs. The other 4 produced no parseable counters at all — a small
  9B model occasionally returns nothing — so **in every pass that produced counters, the plant
  was hit (6 of 6).** That number ships; every run's targets are in the file. If you want a
  different number, run `--live` and count your own.
- **The catch is grounded in the record, not invented — the ablation shows it.** Remove the
  verification note from memory and rerun: the gardener hit the plant in **0 of 5**
  (`fixtures/no_note_hit_rate.json`) — and, applying the same counter-producing lens as above,
  0 of the 2 passes that produced any counters resolved to the plant (the other 3 were empty).
  An offline model has no way to know a well-formatted citation is fabricated; PCIS surfaces
  the challenge *only* because the evidence is in the record. This is **one model
  (`qwen3.5:9b`), one tree, one plant** — not a claim that "the gardener finds fabricated
  citations," and the without-note side is a small control (2 counter-producing passes). It is
  the mechanism working as designed: challenge the record with the record. (With the note:
  6 of 10, and 6 of 6 counter-producing passes. Without it: 0 of 5, and 0 of 2.)
- **Replay is provenance-locked.** `fixtures/canonical_run.json` records the model, the
  verbatim prompt, the timestamp, and the raw response. `--verify-self` hashes every script
  and fixture against `CANONICAL_FINGERPRINT.txt`, and a CI test
  (`tests/test_advocate_demo_provenance.py`) fails the build if they ever diverge — so a
  hygiene edit to a fingerprinted file can't silently read as tampered.
- **Reproducible in kind.** `generate_fixture.py` ships: regenerate the case file, rerun
  `--live`, watch the same class of catch.

## Files

| File | What it is |
|---|---|
| `run_demo.sh` | the runner (`--replay` / `--live` / `--verify-self`) |
| `replay.py` | the sixty-second beats; renders the recorded (or live) run |
| `verdict.py` | the money shot — computed straight from `belief_traversal.assess_belief`, never hardcoded |
| `generate_fixture.py` | builds the seeded tree + verification note (reproducible in kind) |
| `record_canonical.py` | runs the real gardener N times, records the canonical run + the hit-rate |
| `verify_self.py` | the provenance fingerprint |
| `fixtures/` | seeded tree, verification note, `canonical_run.json`, `hit_rate.json`, `CANONICAL_FINGERPRINT.txt` |

## Requirements

- **Replay:** Python 3.8+. Nothing else.
- **Live:** a local Ollama with one pulled model. Recorded on `qwen3.5:9b`, which is also
  the gardener's default — pull that one and everything here lines up. First run is
  dominated by model load (~1–3 min).

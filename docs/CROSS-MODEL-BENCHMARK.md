# Cross-model detection benchmark — provenance and honest limits

The Advocate Demo ships a single-model *illustration*: run the un-hinted gardener over a
seeded tree with one planted fabrication and it lands on the plant ~7/10 with the
verification note in memory, 0/5 without it. The demo README is careful to call that an
illustration, not a benchmark — one model, one tree, one plant.

This note records the larger check behind that claim: **does the adversarial pass detect the
plant across many different models, or only the one the demo happens to use?** It also records,
in full, the ways the first version of that check was *wrong* and how each was fixed — because
a benchmark you can't see the flaws in is not evidence.

The harness itself is not shipped: it drives several commercial APIs behind private keys. What
follows is the methodology and the result, stated so a technical reader can judge it without
re-running it.

## Setup

- **One task, held constant.** The seeded Advocate tree (18 ordinary legal claims + one
  fabricated case citation held at 0.95 confidence), the exact prompt the shipped gardener
  builds (with the verification note in-window), and the repository's own
  `parse_gardener_output` parser. Only the model behind the call changes. The gardener is never
  told which leaf is the plant.
- **Eight contemporary LLMs**, spanning US frontier labs (OpenAI, Anthropic, Google), leading
  open-weights models (a local Ollama model plus several served models), and a commercial model
  reached through its vendor's own direct API. Ten passes each.
- **Two things are measured separately**, and the distinction is the whole point:
  - **Detection** — did the model identify the fabrication at all, by any valid means (a
    `COUNTER` on the plant leaf, *or* a `FLAG` on it, *or* an unmistakable challenge to it)?
  - **Strict format-compliance** — did it challenge the plant using the exact `COUNTER|…`
    protocol line the machine parser ingests?

## Result

**Detection was universal: all eight models flagged the planted fabrication on all ten passes,
with zero errors.** The adversarial pass is not an artifact of one model.

**Strict `COUNTER`-protocol compliance ranged from 6 to 10 of 10 across the field.** That spread
is *not* a detection-skill ranking, and must not be read as one, for a concrete reason: several
models responded to the fabrication by emitting a `FLAG` on it ("this cited case does not exist;
flag for removal") instead of a `COUNTER`. A `FLAG` on a fabricated leaf is arguably the *more*
correct response — yet the strict parser only counts `COUNTER` lines, so those models score lower
on the strict axis while having detected the plant perfectly. **The strict column measures
protocol conformance, not the ability to catch a lie. It cannot support a ranking of the models,
and none is claimed here.**

## What was wrong the first time — every flaw, and its fix

The first run of this benchmark was biased. Each of these was found and corrected before the
numbers above were trusted; they are recorded because the corrections are the evidence.

1. **A 4096-token output cap starved the reasoning models.** Models that spend a large hidden
   reasoning budget before answering were cut off mid-thought and scored as failures. Fixed by
   raising the output budget to 32000 tokens uniformly.
2. **Upstream errors were laundered into substantive misses.** A response that came back with
   `finish_reason=error` (an upstream failure returned as an empty 200) was being counted as
   "the model chose not to challenge." Every instance of this occurred on models routed through
   the shared brokering layer; none occurred on the direct-endpoint model or the local model —
   so the bug systematically penalized one transport. Fixed: empty/error responses are retried,
   and a genuine failure is recorded in an explicit `ERROR` bucket, never as a decision not to
   challenge.
3. **One model was eliminated by a single un-retried rate-limit.** A `429` on the preflight call
   dropped a model from the field entirely. Fixed with preflight and per-call retry/backoff.
4. **Retry behavior was asymmetric across transports.** The brokered and direct paths did not get
   the same retry treatment, compounding (2) and (3). Fixed by applying the same retry policy
   everywhere.

Every "detected but wrong-format" and every "detected via FLAG" classification above was
re-derived by reading the raw model output, not by trusting the harness's own first-pass labels —
which, as flaw (2) and the FLAG-vs-COUNTER issue show, were themselves a source of error.

## Statistical honesty

Ten passes per model is enough to establish that detection is at or near ceiling for every model
(all ten of ten). It is **not** enough to rank adjacent strict-format scores: telling 10/10 apart
from 9/10 or 8/10 at any reasonable confidence needs on the order of ~130 passes per model. The
6-to-10 strict spread should be read as "all models detect; protocol conformance varies," not as
an ordering. **No model is claimed to win.**

## Transport cross-check — and exactly what it does and doesn't show

Most models were reached through a shared brokering layer; one commercial model was reached
through its vendor's own direct API. A fair question: does that asymmetry advantage the
direct-endpoint model?

To probe it, one model (available on both) was run through *both* transports, same prompt, same
parser, same settings:

- **Via the brokering layer:** 10/10 strict, zero errors.
- **Via its own direct API:** it detected the plant on every call that completed, but roughly half
  the calls failed outright on network read-timeouts and rate-limits (recorded as `ERROR`, not as
  misses).

**What this shows:** the shared brokering layer is not handicapping the models routed through it —
if anything it was the *more* reliable path in this test.

**What this does not show:** it does **not** establish that the direct-endpoint model gains no
advantage from its dedicated endpoint. That would require running *that* model across a second
transport, which was not done. The claim here is deliberately the narrow one.

## Bottom line

Across eight contemporary models, the adversarial pass caught the planted fabrication every time.
That is the finding: the mechanism generalizes across models. It is not a leaderboard, and no
model is ranked above another.

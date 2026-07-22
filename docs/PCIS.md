# PCIS — Persistent Cognitive Integrity System

_The case for an AI substrate that challenges its own beliefs — not just remembers them, and not just proves it didn't edit the record._

Like the amnesiac in *Memento*, an AI agent runs on a record it can't vouch for. His notes are his continuity, which means whoever edits the notes edits him — and he can be led to write a lie in his own hand, read it later, and believe it completely. No inner alarm fires: the forgery arrived through the trusted channel, his own record.

An AI substrate has the same vulnerability, and by default a worse version of it — the process that writes the record and the process that reads it are the same. It can amend its own past and then sincerely report the amended version. Not lying, exactly. Something worse: no way to know it was rewritten.

## Two questions

Most AI memory systems ask **"What should I remember?"** — retrieval, ranking, recall. A newer class of audit ledgers asks **"Was the log edited?"** — signatures, hash chains, tamper-evidence.

PCIS asks a third question, the one neither answers: **"Should I still believe it?"**

A perfectly signed, un-tampered log can still be quietly wrong — full of overconfident claims that no longer hold, contradictions no one caught, conclusions the evidence never supported. Proving the record wasn't *edited* says nothing about whether it's *sound*. An intact record and a stale belief coexist just fine. That gap — between an honest record and a justified belief — is what PCIS is built for.

## Tamper-evidence is the floor, not the point

Tamper-evidence is a solved, commodity property. Certificate Transparency, Sigstore/Rekor, and a field of audit ledgers — ChainProof, SignLedger, Capsule Protocol, Signatrust, VCP — all ship append-only, hash-linked, signed records, and say so plainly. PCIS uses the same machinery: a Merkle-rooted tree, append-only, every state fingerprinted from content up. That part is mundane and necessary. It is the floor.

What most of them don't do is test whether the claim still holds. That is the part PCIS is built around.

## The mechanism: a record that attacks itself

On every maintenance pass, an adversarial process — the **gardener** — reads the knowledge tree and attacks its highest-confidence claims: the branches where confidence runs uniformly high and spread runs low, the places most likely to have become echo chambers. It runs on a local model, with the last few days of session memory as context, and it is told to hunt contradictions and weak reasoning — not to confirm what's already there.

Where a challenge holds, it becomes a permanent **COUNTER** entry: a recorded objection, hash-linked like everything else, never overwriting the claim it challenges. Routine counters on operational branches commit automatically; challenges that touch the agent's constitutional beliefs — and new links between claims — are staged for a human to review and apply. Nothing is silently rewritten in either case. The record only grows, and it grows more honest.

This is the line between PCIS and a ledger. A ledger immortalizes what it's given and never questions it. PCIS spends its compute attacking its own high-confidence beliefs — so a claim that survives has survived not just tampering, but challenge.

## The honesty boundary: the producer cannot certify itself

There's one more thing a self-challenging record needs, and it's the thing the audit ledgers don't have.

The Merkle root proves the record is internally consistent. A signature over that root proves *who* attested it, and when. In almost every tamper-evident system, the key that makes that signature lives on the same machine as the log — so a compromised host is a compromised ledger: it can rewrite history and re-sign it in a single move.

PCIS refuses that. **The producer cannot certify itself.** The signing key lives off the machine that runs the substrate. The gardener, the tree, the whole runtime can compute the current root and hand off a claim to be signed — but they hold no key, and nothing on the substrate can approve its own record. The agent prepares a claim; it does not approve it. The ratifying party is outside the process that would have to be compromised.

In *Memento*, the missing piece was never a better notebook — it was a second person who couldn't be tattooed. Not because people are more reliable, but because they're *elsewhere*, outside the process a forger would have to own. The off-machine key is that second person. It is not plumbing; it is the one line an attacker who owns the box still cannot cross.

## Why "persistent," and why "cognitive"

The record has to outlive the thing that thinks. Models are transient — swapped for a better, cheaper, or newer one every year. Intelligence is commoditizing and will keep commoditizing, which is exactly why it can't be where the integrity lives. Think of the model as a pianist: they come and go, each with their own training; none of them changes the instrument or the score. PCIS is the instrument. It persists across sessions, crashes, and model swaps, and it's model-agnostic by construction — swap GPT for Claude for a local model and the integrity layer doesn't move.

## What this is not

PCIS proves what an agent *committed to* — a given claim, at a given time, under challenge. It does not prove the claim is true of the world; a pristine record and a hallucination can coexist, and PCIS catches the second only where the answer contradicts a claim the agent held. It is not equivocation-proof on its own — a dishonest operator could keep two trees — which is why an independent witness is a separate layer, not a promise made here. These limits are deliberate: each belongs in its own layer, and claiming otherwise would be the exact overconfidence PCIS exists to catch.

## Verify it yourself

No trust required — run it on your own machine:

```bash
bash setup.sh     # one-time: initialize a tree
./verify.sh       # re-derives every leaf hash, recomputes the Merkle root
```

```text
Chain root: <recomputed from your tree>
Leaves:     <n>
Status:     ✓ Untampered
```

Change one byte of any leaf's content and run it again — the status flips to `✗ TAMPERED` and names the offending leaf. The check re-derives every hash from content, so a silent edit can't hide.

## The whole of it

An AI can still be wrong about the world. What PCIS refuses to let it do is hold a belief it never challenged, or quietly rewrite the record of what it said — and then certify that record itself.

**Memory is not the problem. Epistemology is.**

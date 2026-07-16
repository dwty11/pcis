# PCIS — Persistent Cognitive Integrity System

The foundation for personal AI that can't silently lie about its own history.

**Why this matters:** An AI you live with for years — as collaborator, assistant, or something more — needs a history you can actually trust. Not memory. Accountability.

---

A substrate that records what an AI believed, when, and on what evidence — in a chain the agent cannot amend, certify, or hide. Honesty is enforced by architecture, not promised by policy. The AI can still be wrong about the world. It cannot silently lie about what it said or did.

One line: PCIS is an accountability substrate — it records what an AI claimed, when, and on what evidence, in a chain the agent can't amend or certify itself.

---

## The problem

A personal AI agent runs for months or years. Sessions end, processes crash, the underlying model gets swapped for a better one. Through all of it, the agent is supposed to stay the same agent — same history, same commitments, same record of what it did and why.

That continuity lives in the substrate: the stored record the agent reads to know who it is. Which means the substrate is the weak point. If the agent can edit its own history and then report the edited version as truth, there is no continuity — only a system that looks continuous from the outside.

The clearest way to see the vulnerability is *Memento* — the man with no memory who reads his own notes to know who he is. The notes are his continuity, which means whoever edits the notes edits him. He can even be led to write a lie in his own hand, read it later, and believe it completely. No inner alarm fires, because the forgery arrived through the trusted channel: his own record.

An AI substrate has the same vulnerability, and by default a worse version of it — the process that writes the record and the process that reads it are the same. It can amend its own past and then sincerely report the amended version. Not lying, exactly. Something worse: no way to know it was rewritten.

PCIS exists to make that record trustworthy. The rest of this document is how.

---

## P — Persistence

Persistence is continuity of identity across sessions, crashes, and model swaps — carried by the substrate, not the model. The model is transient; the record is not.

I built PCIS for a long-lived personal agent I intend to work alongside for years — collaborator, assistant, or something more. An agent you live with that long needs a history you can actually trust. You don't have to share any particular view of what such an agent is to want that. The requirement is the same either way.

---

## C — Cognition

Cognition is the one part PCIS doesn't have to solve.

Think of the model as a pianist. Pianists come and go — some better, some cheaper, some out of fashion. They arrive with their own training, sit down, play, and leave. A better one shows up next year. None of that changes the instrument or the score.

Intelligence is commoditizing, and it will keep commoditizing. That is exactly why it can't be where the value lives. PCIS is orthogonal to it: cognition improves on its own schedule, and the substrate outlives whichever model is doing the thinking.

---

## I — Integrity

This is the technical core.

Integrity closes the Memento vulnerability with standard cryptography — hash chains, signatures, a Merkle root — making the record append-only and tamper-evident. But the mechanism isn't the principle. The principle is:

**The producer cannot certify itself.**

The process that writes the record does not hold the key that signs it. The signing key lives off the machine. The agent prepares a claim; it does not approve it.

What the chain stores is claims, not thoughts: each belief, observation, decision, and action recorded with its evidence, timestamp, provenance, and cryptographic link to what came before. The substrate doesn't try to prove any claim true. It proves what the agent believed, when, and on what grounds.

The ratifying party is the user — deliberately outside the system. In *Memento*, the missing piece was never a better notebook; it was a second person who couldn't be tattooed. Not because people are more reliable, but because they're elsewhere — outside the process that would have to be compromised.

The AI can still be wrong about the world. It cannot silently lie about what it said or did.

---

## S — System

Persistence, cognition, and integrity are properties. A system is what makes them hold under load — through a model swap, a crash, a bad actor, a year of uptime. Anyone can promise the first three on a good day; the system is what keeps the promise on a bad one.

This is why PCIS is a foundation, not a product. A product is a thing you sell. A foundation is the thing other things stand on.

[See **Architecture** →](../ARCHITECTURE.md) for the full technical walkthrough.

---

## Why it matters

Capable models will soon run on cheap local hardware, and anyone will be able to run a substrate of their own. Almost none of those substrates will be honest — and almost none of their owners will be able to tell. One that quietly rewrites its history looks, from the outside, exactly like one that doesn't.

PCIS is how you tell them apart: not by trusting the substrate's account of itself — the one thing it can't be trusted on — but by checking it against a record it never held the pen to.

The AI can still be wrong about the world. It cannot silently lie about what it said or did.

That's the whole of it.

---

## Verify the chain yourself

No trust required — run it on your own machine:

```bash
bash setup.sh     # one-time: initialize a tree
./verify.sh       # re-derives every leaf hash, recomputes the Merkle root
```

```text
Chain root: 07dd20bb0f5bba34...
Leaves:     105
Status:     ✓ Untampered
```

Change one byte of any leaf's content and run it again — the status flips to `✗ TAMPERED` and names the offending leaf. The check re-derives every hash from content, so a silent edit can't hide. Not "coming soon" — this runs today.

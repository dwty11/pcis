# Tamper protocol — how the integrity legend is verified

The provenance legend in `index.html` is the one place prose does work no value
can do: it explains **why there are two indicators**. That is not a description
of any computed value, so it cannot be derived from one — and it is the text
that shipped wrong twice.

So it carries a rule:

> **Every sentence must be verifiable by doing.** A reader must be able to
> produce the described behaviour. Anything that cannot be demonstrated comes
> out — cut, not reworded.

This file is that rule's mechanism. The legend is checked against reality by
performing these steps, rather than by being asserted next to code. **A change
to the legend has to survive this protocol; a sentence with no step here does
not belong in it.**

Run against a scratch copy, never the shipped tree:

```sh
cp -R demo /tmp/pcis-tamper/demo && ln -s "$PWD/core" /tmp/pcis-tamper/core
OLLAMA_HOST=http://127.0.0.1:1 PCIS_BASE_DIR=/tmp/pcis-tamper \
  python3 /tmp/pcis-tamper/demo/server.py --port 5599
```

`OLLAMA_HOST` pointed at a dead port forces the keyword-fallback path, which is
the documented first-run state and the one a stranger actually gets.

---

## §1 — Naive tamper: integrity catches it

**Legend sentence:** *"Edit a claim in the tree and leave its hash alone:
integrity turns red on that card."*

1. In `demo_tree.json`, prepend text to some leaf's `content`. Leave its `hash`.
2. Run a query on the Query tab that returns that leaf.

**Expect:** the card's hash line reads `✗ CONTENT DOES NOT MATCH THIS HASH` in
red. The boot tab reads `MODIFIED`.

**Why it works:** `verify_tree_integrity` recomputes `hash_leaf(content, branch,
created)` per leaf. Editing content without rehashing breaks that equality.

---

## §2 — Rehashing tamper: integrity is defeated, an earlier trace is not

**Legend sentence:** *"Edit it and recompute its hash: integrity goes quiet, but
open an earlier record in the ledger below and that leaf reads changed since
trace."*

1. Run a query FIRST, so a record exists from before the tamper.
2. Edit a leaf's `content` **and** set `hash` to
   `hash_leaf(new_content, branch, created)`.
3. Re-run the query — integrity now reads clean.
4. Expand **recent retrieval traces** and open the record from step 1.

**Expect:** step 3's card shows clean integrity. Step 4's record shows that leaf
as `changed since trace`.

**Why it works:** `_classify_all` hashes each leaf's *current* content and
compares it to the hash recorded at retrieval time. It never reads the tree
root, so detection does not depend on the root moving — **and it does not
move**: `compute_root_hash` derives from *stored branch hashes*, so a leaf
rehash leaves it byte-identical.

> The cut sentence lived here. It said this worked *because the root moves*.
> Nobody could produce that, and it stayed wrong for two rounds because no
> action was ever attached to it. That is what this protocol exists to prevent.

---

## §3 — Fresh state: both muted is correct

**Legend sentence:** *"On a fresh clone with a fresh retrieval, both read muted,
and that is correct — nothing has elapsed yet to check against."*

1. Fresh copy, no tampering. Run one query.

**Expect:** integrity muted (`content matches this hash`), chip muted
(`no elapsed check`). Nothing green.

**Why it works:** the trace was drawn from the tree and the tree has not changed
since, so re-verifying compares the tree to itself. A comparison that cannot
fail is not reported as a pass.

---

## §4 — The check cannot vouch for itself

Not a legend sentence — a scope limit stated in the boot explainer, recorded so
nobody mistakes §1 for more than it is.

`server.py` is in its own tracked set, so a tampered `server.py` could report
`OK` for itself. Catching that means comparing hashes from outside this page:

```sh
shasum -a 256 demo/server.py && python3 -c "import json;print(json.load(open('demo/demo_manifest.json'))['files']['server.py'])"
```

Equally: neither check distinguishes an authorised edit from tampering. They
establish that bytes moved since someone last vouched for them, and nothing more.

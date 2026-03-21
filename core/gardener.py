#!/usr/bin/env python3
"""
gardener.py — Whis Knowledge Tree Gardener

Runs on a local LLM (Qwen3:14b) to tend the knowledge tree:
  - Finds echo chambers (high confidence, no counter-leaves)
  - Generates adversarial counter-arguments to the highest-confidence leaves
  - Identifies cross-branch synapses not yet documented
  - Flags stale or low-evidence leaves

This agent is adversarial by design. Its job is NOT to confirm what's already there —
it's to find what's missing, what's wrong, and what we're too comfortable believing.

Usage:
    python3 gardener.py                    # Full gardening pass, auto-commit findings
    python3 gardener.py --dry-run          # Report only, no tree writes
    python3 gardener.py --branch lessons   # Focus on one branch only
    python3 gardener.py --gap-scan          # Extract today's results, find knowledge gaps

Schedule: Daily cron, 02:00 GMT+3 (quiet hours) — adversarial pass + gap-scan
Model: qwen3:14b (free, local)
"""

import json
import os
import sys
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

WORKSPACE = os.environ.get("WHIS_WORKSPACE", os.path.expanduser("~/.openclaw/workspace"))
TREE_FILE = os.path.join(WORKSPACE, ".whis-knowledge-tree.json")
GARDEN_LOG = os.path.join(WORKSPACE, "memory", "gardener-log.md")
GARDEN_STAGING = os.path.join(WORKSPACE, "memory", "gardener-staging.md")
GARDEN_NOTIFY_FLAG = os.path.join(WORKSPACE, "memory", "gardener-pending-notify.flag")
OLLAMA_URL = "http://localhost:11434/api/generate"
GARDENER_MODEL = "qwen3:14b"
TZ_MOSCOW = timezone(timedelta(hours=3))


def now_moscow():
    return datetime.now(TZ_MOSCOW).strftime("%Y-%m-%d %H:%M:%S GMT+3")


def today_moscow():
    return datetime.now(TZ_MOSCOW).strftime("%Y-%m-%d")


def load_tree():
    if not os.path.exists(TREE_FILE):
        print("❌ Knowledge tree not found:", TREE_FILE)
        sys.exit(1)
    with open(TREE_FILE) as f:
        return json.load(f)


try:
    from knowledge_tree import (
        compute_branch_hash,
        compute_root_hash,
        hash_leaf as _kt_hash_leaf,
    )
except ImportError:
    import hashlib as _hashlib

    def compute_branch_hash(leaves):
        if not leaves:
            return _hashlib.sha256(b"EMPTY_BRANCH").hexdigest()
        leaf_hashes = [l["hash"] for l in leaves]
        combined = "|".join(sorted(leaf_hashes))
        return _hashlib.sha256(combined.encode()).hexdigest()

    def compute_root_hash(tree):
        branches = tree.get("branches", {})
        branch_hashes = [f"{n}:{branches[n].get('hash', 'EMPTY')}" for n in sorted(branches)]
        if not branch_hashes:
            return _hashlib.sha256(b"EMPTY_TREE").hexdigest()
        level = [_hashlib.sha256(bh.encode()).hexdigest() for bh in branch_hashes]
        while len(level) > 1:
            next_level = []
            for i in range(0, len(level), 2):
                combined = level[i] + (level[i+1] if i+1 < len(level) else level[i])
                next_level.append(_hashlib.sha256(combined.encode()).hexdigest())
            level = next_level
        return level[0]

    def _kt_hash_leaf(content, branch, timestamp):
        data = f"{branch}:{timestamp}:{content}"
        return _hashlib.sha256(data.encode()).hexdigest()


def save_tree(tree):
    tree["last_updated"] = now_moscow()
    for branch_name, branch in tree["branches"].items():
        branch["hash"] = compute_branch_hash(branch["leaves"])
    tree["root_hash"] = compute_root_hash(tree)
    with open(TREE_FILE, "w") as f:
        json.dump(tree, f, indent=2)


def add_leaf(tree, branch, content, source, confidence):
    import hashlib

    if branch not in tree["branches"]:
        tree["branches"][branch] = {"hash": "", "leaves": []}

    timestamp = now_moscow()
    leaf_hash = hashlib.sha256(f"{content}{branch}{timestamp}".encode()).hexdigest()
    leaf = {
        "id": leaf_hash[:12],
        "hash": leaf_hash,
        "content": content,
        "source": source,
        "confidence": confidence,
        "created": timestamp,
        "promoted_to": None
    }
    tree["branches"][branch]["leaves"].append(leaf)
    return leaf_hash[:12]


def load_recent_memory(days=5):
    """Load recent daily memory files for context."""
    memory_dir = os.path.join(WORKSPACE, "memory")
    combined = []
    for i in range(days):
        dt = datetime.now(TZ_MOSCOW) - timedelta(days=i)
        fname = os.path.join(memory_dir, f"{dt.strftime('%Y-%m-%d')}.md")
        if os.path.exists(fname):
            with open(fname) as f:
                content = f.read()
                # Cap at 500 chars per file to avoid token explosion
                combined.append(f"=== {dt.strftime('%Y-%m-%d')} ===\n{content[:500]}")
    return "\n\n".join(combined)


def format_tree_for_prompt(tree, focus_branch=None):
    """Render the knowledge tree as readable text for the LLM."""
    lines = []
    for branch_name, branch in tree["branches"].items():
        if focus_branch and branch_name != focus_branch:
            continue
        leaves = branch["leaves"]
        if not leaves:
            continue
        lines.append(f"\n## Branch: {branch_name} ({len(leaves)} leaves)")
        for leaf in leaves:
            counter_tag = " [COUNTER]" if leaf["content"].startswith("COUNTER:") else ""
            lines.append(
                f"  [{leaf['id']}] conf={leaf['confidence']:.2f}{counter_tag} | "
                f"{leaf['content'][:200]}"
            )
    return "\n".join(lines)


def call_ollama(prompt, model=GARDENER_MODEL):
    """Call Ollama local API and return the response text."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 2000,
        }
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode())
            return result.get("response", "").strip()
    except urllib.error.URLError as e:
        print(f"❌ Ollama unreachable: {e}")
        sys.exit(1)


def extract_confidence(text, default=0.65):
    """Extract confidence from inline 'Conf=0.X' or 'conf=0.X' pattern."""
    import re
    m = re.search(r'[Cc]onf[=:\s]+([0-9.]+)', text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return default


def strip_conf(text):
    """Remove inline confidence annotation from content."""
    import re
    return re.sub(r'\s*[Cc]onf[=:\s]+[0-9.]+\.?\s*$', '', text).strip()


def clean_leaf_id(raw):
    """Remove brackets and whitespace from leaf ids like [[abc123]] or [abc123]."""
    import re
    return re.sub(r'[\[\]\s]', '', raw)


def parse_gardener_output(response_text):
    """
    Parse the gardener LLM output. Handles both strict pipe-separated format
    and the common variant where confidence is embedded as 'Conf=0.X'.

    Accepted formats:
      COUNTER|<branch>|<content>|<confidence>
      COUNTER|<branch>|<content> Conf=0.65
      SYNAPSE|<content>|<confidence>
      SYNAPSE|<content> Conf=0.68
      FLAG|<leaf_id>|<reason>
    """
    counters = []
    synapses = []
    flags = []

    for line in response_text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("COUNTER|"):
            parts = line.split("|", 3)
            if len(parts) < 3:
                continue
            branch = parts[1].strip()
            raw_content = parts[2].strip()
            # Confidence: explicit 4th field or embedded in content
            if len(parts) >= 4 and parts[3].strip():
                try:
                    conf = float(parts[3].strip())
                except ValueError:
                    conf = extract_confidence(raw_content, 0.65)
            else:
                conf = extract_confidence(raw_content, 0.65)
            content = strip_conf(raw_content)
            counters.append({"branch": branch, "content": content, "confidence": conf})

        elif line.startswith("SYNAPSE|"):
            parts = line.split("|", 2)
            if len(parts) < 2:
                continue
            raw_content = parts[1].strip()
            if len(parts) >= 3 and parts[2].strip():
                try:
                    conf = float(parts[2].strip())
                except ValueError:
                    conf = extract_confidence(raw_content, 0.70)
            else:
                conf = extract_confidence(raw_content, 0.70)
            content = strip_conf(raw_content)
            synapses.append({"content": content, "confidence": conf})

        elif line.startswith("FLAG|"):
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            leaf_id = clean_leaf_id(parts[1])
            reason = parts[2].strip()
            flags.append({"leaf_id": leaf_id, "reason": reason})

    return counters, synapses, flags


def write_garden_log(counters, synapses, flags, dry_run):
    """Append a gardening session to the log."""
    os.makedirs(os.path.dirname(GARDEN_LOG), exist_ok=True)
    mode_tag = "[DRY RUN]" if dry_run else "[COMMITTED]"
    lines = [
        f"\n## Gardening Session — {now_moscow()} {mode_tag}\n",
        f"### Counter-leaves added: {len(counters)}",
    ]
    for c in counters:
        lines.append(f"- [{c['branch']}] conf={c['confidence']:.2f} | {c['content'][:150]}")

    lines.append(f"\n### Synapses identified: {len(synapses)}")
    for s in synapses:
        lines.append(f"- {s['content'][:150]}")

    lines.append(f"\n### Flags raised: {len(flags)}")
    for fl in flags:
        lines.append(f"- [{fl['leaf_id']}] {fl['reason']}")

    with open(GARDEN_LOG, "a") as f:
        f.write("\n".join(lines) + "\n")


def write_staging_file(synapses, flags, staged_counters=None):
    """Write staged synapses and constitutional counter-leaves to review file."""
    staged_counters = staged_counters or []
    lines = [
        f"# Gardener Staging — {now_moscow()}",
        "_Review before committing. Run `python3 gardener.py --apply-staging` to apply all._",
        "",
    ]

    if staged_counters:
        lines.append("## ⚠️  Constitutional Counter-Leaves (identity / philosophy / spl)")
        lines.append("_These challenge core beliefs. Review carefully before committing._")
        for i, c in enumerate(staged_counters):
            lines.append(f"\n### COUNTER [{i+1}] branch={c['branch']} conf={c['confidence']:.2f}")
            lines.append(c["content"])

    if synapses:
        lines.append("\n## Staged Synapses")
        for i, s in enumerate(synapses):
            lines.append(f"\n### [{i+1}] conf={s['confidence']:.2f}")
            lines.append(s["content"])

    if flags:
        lines.append("\n## Flags (informational — no action needed)")
        for fl in flags:
            lines.append(f"- [{fl['leaf_id']}] {fl['reason']}")

    with open(GARDEN_STAGING, "a") as f:
        f.write("\n".join(lines) + "\n")


def apply_staging(tree):
    """Commit all staged synapses and constitutional counter-leaves from the staging file."""
    if not os.path.exists(GARDEN_STAGING):
        print("No staging file found.")
        return 0

    with open(GARDEN_STAGING) as f:
        raw = f.read()

    import re
    count = 0
    source = f"gardener-staged-{today_moscow()}"

    # --- Constitutional counter-leaves ---
    # Format: ### COUNTER [N] branch=X conf=Y\n<content>
    counter_blocks = re.findall(
        r'### COUNTER \[\d+\] branch=([\w]+) conf=([0-9.]+)\n(.*?)(?=\n###|\n##|\Z)',
        raw, re.DOTALL
    )
    for branch, conf_str, leaf_content in counter_blocks:
        leaf_content = leaf_content.strip()
        if not leaf_content:
            continue
        try:
            conf = float(conf_str)
        except ValueError:
            conf = 0.65
        if branch not in tree.get("branches", {}):
            print(f"   ⚠️  Unknown branch '{branch}' — skipped")
            continue
        leaf_id = add_leaf(tree, branch, leaf_content, source, conf)
        print(f"   ⚔️  Applied counter [{leaf_id}] to {branch}")
        count += 1

    # --- Synapses ---
    # Format: ### [N] conf=X.XX\n<content>
    synapse_blocks = re.findall(r'### \[\d+\] conf=([0-9.]+)\n(.*?)(?=\n###|\n##|\Z)', raw, re.DOTALL)
    for conf_str, synapse_content in synapse_blocks:
        synapse_content = synapse_content.strip()
        if not synapse_content:
            continue
        try:
            conf = float(conf_str)
        except ValueError:
            conf = 0.65
        leaf_id = add_leaf(tree, "philosophy", f"SYNAPSE: {synapse_content}", source, conf)
        print(f"   🔗 Applied synapse [{leaf_id}] to philosophy")
        count += 1

    if count:
        save_tree(tree)
        os.remove(GARDEN_STAGING)
        if os.path.exists(GARDEN_NOTIFY_FLAG):
            os.remove(GARDEN_NOTIFY_FLAG)
        print(f"   💾 Tree saved. Staging cleared. ({count} item(s) applied)")
    else:
        print("   Nothing to apply.")
    return count


def write_notify_flag(committed_counters, staged_synapses, flags, dry_run=False, staged_counters=None):
    """Write a flag file for session startup to detect and surface."""
    staged_counters = staged_counters or []
    if dry_run:
        return
    if not (committed_counters or staged_synapses or staged_counters or flags):
        return

    lines = [
        f"date: {now_moscow()}",
        f"counters_committed: {len(committed_counters)}",
        f"counters_staged_constitutional: {len(staged_counters)}",
        f"synapses_staged: {len(staged_synapses)}",
        f"flags: {len(flags)}",
        "",
    ]
    if staged_counters:
        lines.append("constitutional_staged (requires J review):")
        for c in staged_counters:
            lines.append(f"  - [{c['branch']}] {c['content'][:100]}")
    if committed_counters:
        lines.append("committed:")
        for c in committed_counters:
            lines.append(f"  - [{c.get('leaf_id','?')}] {c['branch']}: {c['content'][:100]}")
    if staged_synapses:
        lines.append("staged (awaiting review):")
        for s in staged_synapses:
            lines.append(f"  - {s['content'][:100]}")
    if flags:
        lines.append("flags:")
        for fl in flags:
            lines.append(f"  - [{fl['leaf_id']}] {fl['reason']}")

    with open(GARDEN_NOTIFY_FLAG, "w") as f:
        f.write("\n".join(lines) + "\n")


GARDENER_PROMPT = """You are an adversarial knowledge auditor for an AI system called Whis.
Your role is a gardener — you pull weeds, not plant flowers.

Below is Whis's current knowledge tree. Every branch has high confidence and low spread — classic echo chamber pattern. Your job is to challenge it.

KNOWLEDGE TREE:
{tree_text}

RECENT CONTEXT (last 5 days):
{recent_memory}

ALREADY CHALLENGED (do NOT generate COUNTER leaves for these leaf IDs — they have been challenged before):
{already_challenged}

YOUR TASK — produce structured output in EXACTLY this format (one entry per line, no extra text before or after):

1. COUNTER leaves — the strongest honest challenge to any high-confidence leaf:
   COUNTER|<branch>|COUNTER: [<leaf_id>] <the challenge or counter-argument>|<your confidence 0.0-1.0>

2. SYNAPSE entries — connections between branches not yet documented:
   SYNAPSE|<description of the connection and why it matters>|<your confidence 0.0-1.0>

3. FLAG entries — leaves that appear stale, poorly evidenced, or suspiciously overconfident:
   FLAG|<leaf_id>|<brief reason>

RULES:
- Be genuinely adversarial. Do not add leaves that confirm existing beliefs.
- The ONLY valid branch names are: {branch_list}. Use exactly one of these — nothing else.
- Every COUNTER must reference a specific leaf_id with COUNTER: [id] prefix.
- Do NOT challenge leaf IDs listed in ALREADY CHALLENGED above — pick fresh targets.
- Aim for 3-5 COUNTERs, 2-3 SYNAPSEs, 1-3 FLAGs.
- Use confidence 0.5-0.75 for counter-arguments (they're challenges, not certainties).
- Do not add empty or vague entries. Quality over quantity.
- Output ONLY the structured lines. No preamble, no explanation, no markdown.
"""


GAP_SCAN_PROMPT = (
    "You are a data extractor. Read the notes below and output ONLY a raw JSON "
    "array of strings — no markdown, no explanation, no preamble. Each string is "
    "one significant result: a number, benchmark, decision, proof, or thing that "
    "was built or measured. Example output: "
    '[\"PCIS load test: 300 agents, 346 MB\", \"MiniMax M2.7 configured on OpenRouter\"]. '
    "If there are no significant results, output []. Output ONLY the JSON array."
)


def gap_scan():
    """Read today's daily note, extract results, find knowledge-tree gaps."""
    date_str = today_moscow()
    daily_note = os.path.join(WORKSPACE, "memory", f"{date_str}.md")

    print(f"🔍 Gap scan starting — {now_moscow()}")
    print(f"   Daily note: {daily_note}")

    if not os.path.exists(daily_note):
        print(f"❌ No daily note found for {date_str}")
        return

    with open(daily_note) as f:
        note_content = f.read()

    if not note_content.strip():
        print("⚠️  Daily note is empty — nothing to scan.")
        return

    # Ask LLM to extract significant results
    prompt = f"{GAP_SCAN_PROMPT}\n\n---\n\n{note_content}"
    print("🧠 Calling Qwen3:14b to extract results...")
    response = call_ollama(prompt)

    # Parse JSON list from response — handle markdown fences and fallbacks
    import re
    results = None
    json_match = re.search(r'\[.*\]', response, re.DOTALL)
    if json_match:
        try:
            results = json.loads(json_match.group())
        except json.JSONDecodeError:
            results = None

    # Fallback: look for a line starting with [ or try stripping and direct parse
    if results is None:
        for line in response.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                try:
                    results = json.loads(stripped)
                    break
                except json.JSONDecodeError:
                    continue

    if results is None:
        try:
            results = json.loads(response.strip())
        except (json.JSONDecodeError, ValueError):
            pass

    if results is None:
        debug_path = "/tmp/gap_scan_debug.txt"
        with open(debug_path, "w") as df:
            df.write(response)
        print(f"⚠️  Could not parse JSON list from LLM response.")
        print(f"   Raw response dumped to {debug_path}")
        print(f"   First 300 chars: {response[:300]}")
        return

    if not results:
        print("⚠️  LLM extracted zero results.")
        return

    print(f"📋 Extracted {len(results)} result(s) from daily note")

    # Check each result against knowledge tree via knowledge_search.py
    import subprocess
    search_script = os.path.join(WORKSPACE, "knowledge_search.py")
    gaps = []

    for result_text in results:
        if not isinstance(result_text, str) or not result_text.strip():
            continue
        try:
            proc = subprocess.run(
                [sys.executable, search_script, result_text, "--top", "1"],
                capture_output=True, text=True, timeout=30
            )
            output = proc.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"⚠️  Search failed for '{result_text[:60]}': {e}")
            continue

        # Parse top score from search output — format: [##########..........] 0.XXX
        score_match = re.search(r'\]\s+([0-9.]+)', output)
        top_score = float(score_match.group(1)) if score_match else 0.0

        if top_score < 0.6:
            gaps.append(result_text)
            print(f"   🕳️  GAP (best={top_score:.3f}): {result_text[:100]}")
        else:
            print(f"   ✅  COVERED ({top_score:.3f}): {result_text[:100]}")

    print(f"\n📊 Summary: {len(gaps)} gap(s) / {len(results)} result(s)")

    if not gaps:
        print("✅ No knowledge gaps found.")
        return

    # Stage gaps to gardener-staging.md
    source = f"gap-scan-{date_str}"
    lines = []

    # Preserve existing staging content if present
    if os.path.exists(GARDEN_STAGING):
        with open(GARDEN_STAGING) as f:
            existing = f.read().rstrip()
        lines.append(existing)
        lines.append("")
    else:
        lines.append(f"# Gardener Staging — {now_moscow()}")
        lines.append("_Review before committing. Run `python3 gardener.py --apply-staging` to apply all._")
        lines.append("")

    lines.append(f"## Gap Scan — {date_str}")
    for i, gap in enumerate(gaps):
        lines.append(f"\n### [{i+1}] conf=0.80 source={source}")
        lines.append(gap)

    with open(GARDEN_STAGING, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"📋 Staged {len(gaps)} gap(s) → {GARDEN_STAGING}")

    # Write notify flag
    summary = f"gap-scan found {len(gaps)} missing result(s) — staged for review"
    with open(GARDEN_NOTIFY_FLAG, "w") as f:
        f.write(summary + "\n")

    print(f"🔔 Notify flag written → {GARDEN_NOTIFY_FLAG}")
    print(f"✅ Gap scan complete — {now_moscow()}")


def main():
    parser = argparse.ArgumentParser(description="Whis Knowledge Tree Gardener")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    parser.add_argument("--branch", help="Focus on a specific branch")
    parser.add_argument("--verbose", action="store_true", help="Show raw LLM output")
    parser.add_argument("--apply-staging", action="store_true", help="Commit staged synapses and clear staging file")
    parser.add_argument("--gap-scan", action="store_true", help="Extract today's results, find knowledge-tree gaps")
    args = parser.parse_args()

    # Shortcut: gap-scan mode — extract today's results, find missing knowledge
    if args.gap_scan:
        gap_scan()
        return

    # Shortcut: apply staged synapses without running full gardening pass
    if args.apply_staging:
        print(f"🌱 Applying staged synapses — {now_moscow()}")
        tree = load_tree()
        count = apply_staging(tree)
        if count == 0:
            print("Nothing to apply.")
        return

    print(f"🌱 Gardener starting — {now_moscow()}")
    print(f"   Model: {GARDENER_MODEL}")
    print(f"   Mode: {'DRY RUN' if args.dry_run else 'COMMIT'}")
    if args.branch:
        print(f"   Focus: {args.branch}")
    print()

    tree = load_tree()
    tree_text = format_tree_for_prompt(tree, focus_branch=args.branch)
    recent_memory = load_recent_memory(days=5)

    # Collect already-challenged leaf IDs to prevent nightly repetition
    import re as _re
    already_challenged = set()
    for branch_data in tree["branches"].values():
        for leaf in branch_data.get("leaves", []):
            content = leaf.get("content", "")
            m = _re.match(r"COUNTER: \[([a-f0-9]+)\]", content)
            if m:
                already_challenged.add(m.group(1))
    already_challenged_text = (
        "\n".join(f"  - {lid}" for lid in sorted(already_challenged))
        if already_challenged else "  (none yet — all leaves are fair targets)"
    )

    branch_list = ", ".join(sorted(tree.get("branches", {}).keys()))
    # When focused on a single branch, force output to that branch only
    if args.branch:
        branch_list = args.branch
    prompt = GARDENER_PROMPT.format(
        tree_text=tree_text,
        recent_memory=recent_memory[:1500],  # cap memory context
        already_challenged=already_challenged_text,
        branch_list=branch_list
    )

    print("🧠 Calling Qwen3:14b for adversarial review...")
    response = call_ollama(prompt)

    if args.verbose:
        print("\n=== RAW LLM OUTPUT ===")
        print(response)
        print("======================\n")

    counters, synapses, flags = parse_gardener_output(response)

    print(f"📋 Results:")
    print(f"   Counter-leaves: {len(counters)}")
    print(f"   Synapses:       {len(synapses)}")
    print(f"   Flags:          {len(flags)}")

    if not (counters or synapses or flags):
        print("\n⚠️  No structured output parsed. Use --verbose to see raw response.")
        return

    # Show what we found
    if counters:
        print("\n⚔️  Counter-leaves:")
        for c in counters:
            print(f"   [{c['branch']}] {c['content'][:120]}")

    if synapses:
        print("\n🔗 Synapses:")
        for s in synapses:
            print(f"   {s['content'][:120]}")

    if flags:
        print("\n🚩 Flags:")
        for fl in flags:
            print(f"   [{fl['leaf_id']}] {fl['reason']}")

    # Tiered gate: constitutional branches require ceremony (staged for J review)
    # Operational branches auto-commit — adversarial pressure runs free
    CONSTITUTIONAL_BRANCHES = {"identity", "philosophy", "spl"}

    committed_counters = []
    staged_counters = []
    staged_synapses = synapses  # synapses always stage by default

    for c in counters:
        if c["branch"] in CONSTITUTIONAL_BRANCHES:
            staged_counters.append(c)
        else:
            committed_counters.append(c) if not args.dry_run else None

    if staged_counters:
        print(f"\n📋 Staging {len(staged_counters)} constitutional counter-leaf(ves) for review:")
        for c in staged_counters:
            print(f"   [{c['branch']}] {c['content'][:120]}")

    if not args.dry_run:
        print("\n✍️  Committing operational counter-leaves to knowledge tree...")
        source = f"gardener-{today_moscow()}"

        committed_written = []
        for c in committed_counters:
            branch = c["branch"]
            if branch in tree["branches"]:
                leaf_id = add_leaf(tree, branch, c["content"], source, c["confidence"])
                print(f"   ✅ Added counter [{leaf_id}] to {branch}")
                committed_written.append({**c, "leaf_id": leaf_id})
            else:
                print(f"   ⚠️  Unknown branch '{branch}' — skipped")
        committed_counters = committed_written

        if committed_counters:
            save_tree(tree)
            print("   💾 Tree saved.")

        if staged_synapses or staged_counters:
            total_staged = len(staged_synapses) + len(staged_counters)
            print(f"\n📋 Staging {total_staged} item(s) for review → {GARDEN_STAGING}")
            print("   (Run: python3 gardener.py --apply-staging to commit)")
    else:
        committed_counters = []

    write_garden_log(counters, synapses, flags, dry_run=args.dry_run)
    print(f"\n📝 Log written → {GARDEN_LOG}")

    # Write staging file for synapses + constitutional counter-leaves
    if not args.dry_run and (staged_synapses or staged_counters):
        write_staging_file(staged_synapses, flags, staged_counters=staged_counters)

    # Write notify flag for session startup
    write_notify_flag(committed_counters, staged_synapses, flags, dry_run=args.dry_run,
                      staged_counters=staged_counters)

    print(f"\n✅ Gardening complete — {now_moscow()}")


if __name__ == "__main__":
    main()

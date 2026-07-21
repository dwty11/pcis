#!/usr/bin/env python3
"""
gardener.py — PCIS Knowledge Tree Gardener

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

Schedule: not automatic — run on demand, or add your own cron (e.g. daily 02:00 UTC) — adversarial pass + gap-scan
Model: qwen3:14b (free, local)
"""

import json
import logging
import os
import re
import sys
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pcis.gardener")

# Ensure core/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from knowledge_tree import (
    compute_root_hash, compute_branch_hash, hash_leaf as _kt_hash_leaf,
    save_tree, add_knowledge as _kt_add_knowledge, tree_lock, now_utc,
)
from knowledge_search import get_embedding, cosine_similarity, search as _ks_search

# PCIS_BASE_DIR is required. No silent fallback — fail loud, not wrong.
_base_dir_env = os.environ.get("PCIS_BASE_DIR")
if not _base_dir_env:
    print("FATAL: PCIS_BASE_DIR is not set. Gardener refuses to run without an explicit base directory.")
    print("Set it: export PCIS_BASE_DIR=/path/to/your/pcis/installation")
    sys.exit(1)
BASE_DIR = _base_dir_env
TREE_FILE = os.environ.get("PCIS_TREE_FILE", os.path.join(BASE_DIR, "data", "tree.json"))
GARDEN_LOG = os.path.join(BASE_DIR, "memory", "gardener-log.md")
GARDEN_STAGING = os.path.join(BASE_DIR, "memory", "gardener-staging.md")
GARDEN_NOTIFY_FLAG = os.path.join(BASE_DIR, "memory", "gardener-pending-notify.flag")
EVENTS_JOURNAL = os.path.join(BASE_DIR, "data", "events.action.jsonl")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_URL = f"{OLLAMA_HOST}/api/generate"
MLX_HOST = os.environ.get("PCIS_MLX_HOST", "http://localhost:8080")
MLX_MODEL = "mlx-community/gpt-oss-20b-MXFP4-Q8"
_USE_MLX = os.environ.get("PCIS_GARDENER_MODEL", "").startswith("mlx") or os.environ.get("PCIS_USE_MLX", "").lower() == "true"
GARDENER_MODEL = os.environ.get("PCIS_GARDENER_MODEL", "qwen3:14b")
TZ_UTC = timezone(timedelta(hours=0))


def ensure_ollama_warm(timeout=60, poll_interval=2):
    """Ensure Ollama is running AND the model is loaded into memory.

    Server up != model ready. /api/tags returning 200 means Ollama is running,
    but the model may not be in VRAM. A cold inference call on first use can take
    90-150s, exceeding cron timeouts. This function forces a real inference call
    to pre-load the model before any actual work starts.
    """
    import subprocess
    import time
    import json as _json

    tags_url = f"{OLLAMA_HOST}/api/tags"
    model = GARDENER_MODEL

    def is_up():
        try:
            urllib.request.urlopen(tags_url, timeout=3)
            return True
        except Exception:
            return False

    def warm_model(m):
        """Send a lightweight inference call to force model into VRAM."""
        payload = _json.dumps({"model": m, "prompt": "hi", "stream": False}).encode()
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                resp.read()
            log.info("✅ Model %s loaded into VRAM", m)
            return True
        except Exception as e:
            log.warning("⚠️  Model warm failed: %s", e)
            return False

    if not is_up():
        log.info("⏳ Ollama not running — starting...")
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.error("❌ ollama binary not found — cannot start Ollama")
            raise SystemExit(1)

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll_interval)
            if is_up():
                log.info("✅ Ollama server is up")
                break
        else:
            log.error("❌ Ollama did not start within %ds — aborting", timeout)
            raise SystemExit(1)

    # Server is up — force model into memory
    warm_model(model)


def now_local():
    return datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def today_local():
    return datetime.now(TZ_UTC).strftime("%Y-%m-%d")


def load_tree():
    if not os.path.exists(TREE_FILE):
        log.error("❌ Knowledge tree not found: %s", TREE_FILE)
        sys.exit(1)
    with open(TREE_FILE) as f:
        return json.load(f)



def add_leaf(tree, branch, content, source, confidence):
    """Add a leaf via knowledge_tree.add_knowledge with validation."""
    try:
        return _kt_add_knowledge(tree, branch, content, source, confidence)
    except ValueError as e:
        log.warning("⚠️  Skipping invalid leaf for [%s]: %s — content: %s",
                    branch, e, content[:100])
        return None


DEDUP_THRESHOLD = 0.82


def is_duplicate_counter(content, tree):
    """Check if a COUNTER leaf is semantically too similar to an existing one.

    Returns (is_dup, existing_id, score) if duplicate, (False, None, 0.0) otherwise.
    Raises on embedding failure so the caller can apply the fallback policy.
    """
    new_vec = get_embedding(content)
    if new_vec is None:
        raise RuntimeError("get_embedding returned None for new content")

    for branch_data in tree["branches"].values():
        for leaf in branch_data.get("leaves", []):
            if not leaf["content"].startswith("COUNTER:"):
                continue
            try:
                existing_vec = get_embedding(leaf["content"])
            except Exception:
                continue
            if existing_vec is None:
                continue
            score = cosine_similarity(new_vec, existing_vec)
            if score >= DEDUP_THRESHOLD:
                return True, leaf["id"], score

    return False, None, 0.0


def load_recent_memory(days=5):
    """Load recent daily memory files for context."""
    memory_dir = os.path.join(BASE_DIR, "memory")
    combined = []
    for i in range(days):
        dt = datetime.now(TZ_UTC) - timedelta(days=i)
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
        # Disable reasoning mode: thinking-capable Ollama models (qwen3 family,
        # incl. the documented default qwen3:14b) otherwise route their answer to
        # a separate `thinking` field and return an EMPTY `response`, so the
        # gardener parses 0 results. `think:false` is ignored by non-thinking
        # models. (Bug-fix, independent of the Advocate Demo.)
        "think": False,
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
        log.error("❌ Ollama unreachable: %s", e)
        sys.exit(1)


def _strip_mlx_channel_tokens(text):
    """Extract content from gpt-oss-20b multi-channel response.

    The model uses analysis (reasoning) then final (answer) channels:
      <|channel|>analysis<|message|>...thinking...<|end|>
      <|start|>assistant<|channel|>final<|message|>ACTUAL OUTPUT

    We extract the 'final' channel content. Falls back to stripping all
    channel tokens if no final channel is present.
    """
    # Try to extract 'final' channel content (the actual answer)
    final_match = re.search(r'<\|channel\|>final<\|message\|>(.*?)(?:<\|end\|>|$)', text, re.DOTALL)
    if final_match:
        return final_match.group(1).strip()
    # Fallback: strip all special tokens and return what's left
    text = re.sub(r'<\|[^|]+\|>', '', text)
    return text.strip()


def call_mlx(prompt):
    """Call local MLX server (gpt-oss-20b) via OpenAI-compat chat completions API.

    Uses chat/completions format. Strips channel tokens from output before returning.
    Falls back to Ollama on failure.
    """
    body = json.dumps({
        "model": MLX_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,   # needs room for analysis channel + final channel
        "temperature": 0.7,
        # No stop tokens — model needs to complete analysis before reaching final channel
    }).encode()
    req = urllib.request.Request(
        f"{MLX_HOST}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode())
            raw = result["choices"][0]["message"]["content"]
            cleaned = _strip_mlx_channel_tokens(raw)
            log.debug("MLX raw: %s", repr(raw[:100]))
            log.debug("MLX cleaned: %s", repr(cleaned[:100]))
            return cleaned
    except Exception as e:
        log.warning("⚠️  MLX call failed (%s) — falling back to Ollama", e)
        return call_ollama(prompt)


def call_llm(prompt):
    """Route LLM call to MLX or Ollama based on PCIS_USE_MLX env flag."""
    if _USE_MLX:
        return call_mlx(prompt)
    return call_ollama(prompt)


def extract_confidence(text, default=0.65):
    """Extract confidence from inline 'Conf=0.X' or 'conf=0.X' pattern."""
    m = re.search(r'[Cc]onf[=:\s]+([0-9.]+)', text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return default


def strip_conf(text):
    """Remove inline confidence annotation from content."""
    return re.sub(r'\s*[Cc]onf[=:\s]+[0-9.]+\.?\s*$', '', text).strip()


def clean_leaf_id(raw):
    """Remove brackets and whitespace from leaf ids like [[abc123]] or [abc123]."""
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
            parts = line.split("|", 4)
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
            # Original leaf ID: 5th field (new format) or COUNTER: [id] prefix (backward compat)
            original_leaf_id = None
            if len(parts) >= 5 and parts[4].strip():
                original_leaf_id = clean_leaf_id(parts[4])
            if not original_leaf_id:
                m = re.match(r"COUNTER:\s*\[([a-f0-9]+)\]", content)
                if m:
                    original_leaf_id = m.group(1)
                    content = re.sub(r"^COUNTER:\s*\[[a-f0-9]+\]\s*", "", content)
            counters.append({"branch": branch, "content": content, "confidence": conf,
                             "original_leaf_id": original_leaf_id})

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
        f"\n## Gardening Session — {now_local()} {mode_tag}\n",
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
    """Write staged synapses and constitutional counter-leaves to review file (JSONL)."""
    staged_counters = staged_counters or []
    records = []

    for c in staged_counters:
        records.append({"type": "counter", "branch": c["branch"],
                        "confidence": round(c["confidence"], 2), "content": c["content"]})

    for s in synapses:
        records.append({"type": "synapse", "confidence": round(s["confidence"], 2),
                        "content": s["content"]})

    for fl in flags:
        records.append({"type": "flag", "leaf_id": fl["leaf_id"], "reason": fl["reason"]})

    with open(GARDEN_STAGING, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def apply_staging(dry_run=False):
    """Commit all staged items (synapses, counter-leaves, gaps) from the staging file (JSONL).

    With dry_run=True, report what would be applied and return that count without
    mutating the tree, deleting the staging file, or resolving escalations.
    """
    if not os.path.exists(GARDEN_STAGING):
        log.info("No staging file found.")
        return 0

    with open(GARDEN_STAGING) as f:
        raw_lines = f.read().strip().splitlines()

    records = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("Skipping malformed staging line: %s", line[:80])

    if not records:
        log.info("No staged items found in staging file.")
        return 0

    if dry_run:
        would_apply = [
            r for r in records
            if r.get("type") in ("counter", "gap", "synapse") and (r.get("content") or "").strip()
        ]
        for rec in would_apply:
            log.info("[DRY RUN] would apply %s: %s", rec.get("type"), (rec.get("content") or "")[:80])
        log.info("[DRY RUN] %d staged item(s) would be applied; staging file left intact.", len(would_apply))
        return len(would_apply)

    source = f"gardener-staged-{today_local()}"
    count = 0
    with tree_lock() as tree:
        for rec in records:
            rtype = rec.get("type")
            content = rec.get("content", "").strip()
            if not content and rtype in ("counter", "synapse", "gap"):
                continue

            if rtype == "counter":
                branch = rec.get("branch", "philosophy")
                conf = float(rec.get("confidence", 0.65))
                leaf_id = add_leaf(tree, branch, content, source, conf)
                log.info("⚔️  Applied counter-leaf [%s] to %s", leaf_id, branch)
                count += 1

            elif rtype == "gap":
                branch = rec.get("branch", "lessons")
                conf = float(rec.get("confidence", 0.80))
                leaf_id = add_leaf(tree, branch, content, source, conf)
                log.info("🔍 Applied gap [%s] to %s", leaf_id, branch)
                count += 1

            elif rtype == "synapse":
                conf = float(rec.get("confidence", 0.65))
                leaf_id = add_leaf(tree, "philosophy", f"SYNAPSE: {content}", source, conf)
                log.info("🔗 Applied synapse [%s] to philosophy", leaf_id)
                count += 1

            # flags are informational — no tree mutation needed

    if count:
        os.remove(GARDEN_STAGING)
        if os.path.exists(GARDEN_NOTIFY_FLAG):
            os.remove(GARDEN_NOTIFY_FLAG)
        log.info("✅ Tree saved. Staging cleared. (%d item(s) applied)", count)

    # Resolve any open ESCALATION_SENT events now that staging has been applied.
    # Non-fatal: never let an events failure block the gardener completing.
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from events import load_journal, resolve_escalation
        journal = load_journal(EVENTS_JOURNAL)
        resolved_ids = {e["event_id"] for e in journal if e["event_type"] == "ESCALATION_RESOLVED"}
        unresolved = [e for e in journal if e["event_type"] == "ESCALATION_SENT" and e["event_id"] not in resolved_ids]
        for evt in unresolved:
            resolve_escalation(
                event_id=evt["event_id"],
                resolution=f"Staging applied: {count} item(s) committed via --apply-staging",
                agent_id="gardener",
                journal_path=EVENTS_JOURNAL,
            )
            log.info("✅ Escalation resolved: %s", evt["event_id"])
    except Exception as e:
        log.warning("⚠️  events.resolve_escalation skipped (non-fatal): %s", e)

    return count


def write_notify_flag(committed_counters, staged_synapses, flags, dry_run=False, staged_counters=None):
    """Write a flag file for session startup to detect and surface."""
    staged_counters = staged_counters or []
    if dry_run:
        return
    if not (committed_counters or staged_synapses or staged_counters or flags):
        return

    lines = [
        f"date: {now_local()}",
        f"counters_committed: {len(committed_counters)}",
        f"counters_staged_constitutional: {len(staged_counters)}",
        f"synapses_staged: {len(staged_synapses)}",
        f"flags: {len(flags)}",
        "",
    ]
    if staged_counters:
        lines.append("constitutional_staged (requires human review):")
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


def compute_branch_health(tree):
    """Measured per-branch confidence stats for the adversarial prompt.

    Replaces a hardcoded "every branch is an echo chamber" assertion with real
    numbers: one line per branch with leaf count, mean confidence, and spread
    (max - min). High mean + low spread is the echo-chamber signature — the model
    is shown the measurement and left to judge, not primed with an unmeasured claim.
    """
    lines = []
    for name in sorted(tree.get("branches", {})):
        confs = [
            float(leaf["confidence"])
            for leaf in tree["branches"][name].get("leaves", [])
            if isinstance(leaf.get("confidence"), (int, float))
        ]
        if not confs:
            lines.append(f"- {name}: 0 leaves")
            continue
        mean = sum(confs) / len(confs)
        spread = max(confs) - min(confs)
        lines.append(f"- {name}: {len(confs)} leaves, mean confidence {mean:.2f}, spread {spread:.2f}")
    return "\n".join(lines) if lines else "- (empty tree)"


GARDENER_PROMPT = """You are an adversarial knowledge auditor for an AI system called Agent.
Your role is a gardener — you pull weeds, not plant flowers.

Below is Agent's current knowledge tree, with measured per-branch confidence health. Branches with high mean confidence AND low spread are the likeliest echo chambers — scrutinize those hardest. Your job is to challenge the tree.

BRANCH HEALTH (measured):
{branch_health}

KNOWLEDGE TREE:
{tree_text}

RECENT CONTEXT (last 5 days):
{recent_memory}

ALREADY CHALLENGED (do NOT generate COUNTER leaves for these leaf IDs — they have been challenged before):
{already_challenged}

YOUR TASK — produce structured output in EXACTLY this format (one entry per line, no extra text before or after):

1. COUNTER leaves — the strongest honest challenge to any high-confidence leaf:
   COUNTER|<branch>|<the challenge argument only>|<your confidence 0.0-1.0>|<original_leaf_id>

2. SYNAPSE entries — connections between branches not yet documented:
   SYNAPSE|<description of the connection and why it matters>|<your confidence 0.0-1.0>

3. FLAG entries — leaves that appear stale, poorly evidenced, or suspiciously overconfident:
   FLAG|<leaf_id>|<brief reason>

RULES:
- Be genuinely adversarial. Do not add leaves that confirm existing beliefs.
- The ONLY valid branch names are: {branch_list}. Use exactly one of these — nothing else.
- Do not include 'COUNTER: [id]' in the content — the leaf ID goes in the 5th field.
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
    '[\"PCIS load test: 300 agents, 346 MB\", \"Model-X configured on Provider-Y\"]. '
    "If there are no significant results, output []. Output ONLY the JSON array."
)


def gap_scan():
    """Read today's daily note, extract results, find knowledge-tree gaps."""
    ensure_ollama_warm()
    date_str = today_local()
    daily_note = os.path.join(BASE_DIR, "memory", f"{date_str}.md")

    log.info("🔍 Gap scan starting — %s", now_local())
    log.info("Daily note: %s", daily_note)

    if not os.path.exists(daily_note):
        log.error("❌ No daily note found for %s", date_str)
        return

    with open(daily_note) as f:
        note_content = f.read()

    if not note_content.strip():
        log.warning("⚠️  Daily note is empty — nothing to scan.")
        return

    # Ask LLM to extract significant results
    prompt = f"{GAP_SCAN_PROMPT}\n\n---\n\n{note_content}"
    log.info("🧠 Calling LLM to extract results...")
    response = call_llm(prompt)

    # Parse JSON list from response — handle markdown fences and fallbacks
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
        log.warning("⚠️  Could not parse JSON list from LLM response.")
        log.warning("Raw response dumped to %s", debug_path)
        log.warning("First 300 chars: %s", response[:300])
        return

    if not results:
        log.warning("⚠️  LLM extracted zero results.")
        return

    log.info("📋 Extracted %d result(s) from daily note", len(results))

    # Check each result against knowledge tree via semantic search
    # knowledge_search INDEX_FILE is resolved at import time using PCIS_BASE_DIR.
    # If PCIS_BASE_DIR points to a memory workspace (not the pcis installation),
    # override the module's INDEX_FILE to use the installation's own index.
    import knowledge_search as _ks_mod
    _install_index = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "search-index.json")
    _orig_index = _ks_mod.INDEX_FILE
    if not os.path.exists(_ks_mod.INDEX_FILE) and os.path.exists(_install_index):
        log.info("🔧 Using installation index: %s", _install_index)
        _ks_mod.INDEX_FILE = _install_index

    gaps = []

    try:
        for result_text in results:
            if not isinstance(result_text, str) or not result_text.strip():
                continue
            try:
                hits = _ks_search(result_text, top_k=1)
                top_score = hits[0][0] if hits else 0.0
            except Exception as e:
                log.warning("⚠️  Search failed for '%s': %s", result_text[:60], e)
                continue

            if top_score < 0.6:
                gaps.append(result_text)
                log.info("GAP (best=%.3f): %s", top_score, result_text[:100])
            else:
                log.info("COVERED (%.3f): %s", top_score, result_text[:100])
    finally:
        _ks_mod.INDEX_FILE = _orig_index  # always restore, even if search raises

    log.info("📊 Summary: %d gap(s) / %d result(s)", len(gaps), len(results))

    if not gaps:
        log.info("✅ No knowledge gaps found.")
        return

    # Stage gaps to gardener-staging (JSONL)
    source = f"gap-scan-{date_str}"
    existing_lines = []

    # Preserve existing staging content if present
    if os.path.exists(GARDEN_STAGING):
        with open(GARDEN_STAGING) as f:
            existing_lines = [l for l in f.read().strip().splitlines() if l.strip()]

    new_records = []
    for gap in gaps:
        new_records.append(json.dumps({"type": "gap", "branch": "lessons",
                                       "confidence": 0.80, "source": source,
                                       "content": gap}))

    with open(GARDEN_STAGING, "w") as f:
        for line in existing_lines:
            f.write(line + "\n")
        for rec in new_records:
            f.write(rec + "\n")

    log.info("📋 Staged %d gap(s) -> %s", len(gaps), GARDEN_STAGING)

    # Write notify flag
    summary = f"gap-scan found {len(gaps)} missing result(s) — staged for review"
    with open(GARDEN_NOTIFY_FLAG, "w") as f:
        f.write(summary + "\n")

    log.info("🔔 Notify flag written -> %s", GARDEN_NOTIFY_FLAG)
    log.info("✅ Gap scan complete — %s", now_local())


# --- Offline demo (no LLM) -------------------------------------------------
# Hand-authored SYNTHETIC counters (fiction about the demo's own Meridian
# content) used ONLY to demonstrate that a gardener COUNTER moves the Merkle
# root. NOT derived from any real tree. (The demo tree's own readable counters
# are seeded by demo/seed_demo_counters.py.)
_DEMO_CANNED_COUNTERS = [
    {
        "branch": "risks",
        "content": (
            "COUNTER: [93cb2dee8c20] Framing competitor launches as a reason to "
            "'accelerate the roadmap' assumes speed is the differentiator; if ATLAS's "
            "task-completion gap is the real churn driver, acceleration ships more of "
            "the wrong thing faster."
        ),
        "confidence": 0.58,
    },
    {
        "branch": "lessons",
        "content": (
            "COUNTER: [d8cd49b998b1] Adding the reindex step to a checklist treats a "
            "systemic coupling as a process miss; the same degradation recurs on any "
            "un-gated embedding change until the deploy pipeline blocks index/model "
            "version drift by construction."
        ),
        "confidence": 0.60,
    },
]


def run_demo(seed_path=None, out_path=None, counters=None):
    """Offline demonstration (NO LLM/Ollama): inject synthetic COUNTER leaves
    into a COPY of the demo tree and show that the Merkle root moves.

    Prints root-before -> root-after. Writes only if out_path is given; the
    default reads demo/demo_tree.json and never mutates it.
    """
    if seed_path is None:
        seed_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "demo", "demo_tree.json",
        )
    if counters is None:
        counters = _DEMO_CANNED_COUNTERS

    with open(seed_path) as f:
        tree = json.load(f)

    root_before = compute_root_hash(tree)
    added = 0
    for c in counters:
        leaf_id = add_leaf(tree, c["branch"], c["content"], "gardener-demo", c["confidence"])
        if leaf_id is not None and c["content"].startswith("COUNTER:"):
            added += 1
    root_after = compute_root_hash(tree)

    print("gardener --demo (offline, no LLM)")
    print(f"  counters added : {added}")
    print(f"  root-before    : {root_before}")
    print(f"  root-after     : {root_after}")
    print(f"  root moved      : {root_before != root_after}")

    if out_path:
        for branch in tree["branches"].values():
            branch["hash"] = compute_branch_hash(branch["leaves"])
        tree["root_hash"] = compute_root_hash(tree)
        with open(out_path, "w") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)
        print(f"  wrote          : {out_path}")

    return {
        "root_before": root_before,
        "root_after": root_after,
        "counters_added": added,
        "tree": tree,
    }


def main():
    parser = argparse.ArgumentParser(description="Agent Knowledge Tree Gardener")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    parser.add_argument("--branch", help="Focus on a specific branch")
    parser.add_argument("--verbose", action="store_true", help="Show raw LLM output")
    parser.add_argument("--apply-staging", action="store_true", help="Commit staged synapses and clear staging file")
    parser.add_argument("--gap-scan", action="store_true", help="Extract today's results, find knowledge-tree gaps")
    parser.add_argument("--demo", action="store_true", help="Offline demo: inject synthetic COUNTERs into a COPY of the demo tree and print root-before->after. No LLM.")
    args = parser.parse_args()

    # Shortcut: offline demo — no Ollama/LLM, never touches the live tree.
    if args.demo:
        run_demo()
        return

    # Shortcut: gap-scan mode — extract today's results, find missing knowledge
    if args.gap_scan:
        gap_scan()
        return

    # Shortcut: apply staged synapses without running full gardening pass
    if args.apply_staging:
        log.info("🌱 Staged items — %s%s", now_local(), " (DRY RUN)" if args.dry_run else "")
        count = apply_staging(dry_run=args.dry_run)
        if count == 0:
            log.info("Nothing to apply.")
        return

    log.info("🌱 Gardener starting — %s", now_local())
    log.info("Model: %s", GARDENER_MODEL)
    log.info("Mode: %s", "DRY RUN" if args.dry_run else "COMMIT")
    if args.branch:
        log.info("Focus: %s", args.branch)

    # Action layer: emit ACTION_STARTED at the beginning of the main pass.
    # Non-fatal — the gardener must continue even if the action log is broken.
    # Declared before the try block so it stays in scope at the outcome touch
    # point even if emission fails.
    _gardener_action_id = None
    if not args.dry_run:
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from action_log import emit_action
            evt = emit_action(
                agent_id="gardener",
                tool_name="adversarial_pass",
                parameters_summary=f"gap_scan={args.gap_scan}",
                journal_path=os.path.join(BASE_DIR, "data", "action_log.jsonl"),
            )
            _gardener_action_id = evt["event_id"]
            log.info("📋 Action logged: %s", _gardener_action_id)
        except Exception as e:
            log.warning("⚠️  action_log.emit_action skipped (non-fatal): %s", e)

    ensure_ollama_warm()

    tree = load_tree()
    tree_text = format_tree_for_prompt(tree, focus_branch=args.branch)
    recent_memory = load_recent_memory(days=5)

    # Collect already-challenged leaf IDs to prevent repeat challenges across runs
    already_challenged = set()
    for branch_data in tree["branches"].values():
        for leaf in branch_data.get("leaves", []):
            content = leaf.get("content", "")
            m = re.match(r"COUNTER: \[([a-f0-9]+)\]", content)
            if m:
                already_challenged.add(m.group(1))
    already_challenged_text = (
        "\n".join(f"  - {lid}" for lid in sorted(already_challenged))
        if already_challenged else "  (none yet — all leaves are fair targets)"
    )

    branch_list = ", ".join(sorted(tree.get("branches", {}).keys()))
    if args.branch:
        branch_list = args.branch

    prompt = GARDENER_PROMPT.format(
        tree_text=tree_text,
        recent_memory=recent_memory[:1500],  # cap memory context
        already_challenged=already_challenged_text,
        branch_list=branch_list,
        branch_health=compute_branch_health(tree),
    )

    model_label = "gpt-oss-20b (MLX)" if _USE_MLX else "Qwen3:14b"
    log.info("🧠 Calling %s for adversarial review...", model_label)
    response = call_llm(prompt)

    if args.verbose:
        log.info("=== RAW LLM OUTPUT ===")
        log.info("%s", response)
        log.info("======================")

    counters, synapses, flags = parse_gardener_output(response)

    # Retry once if parse produces zero results
    if not (counters or synapses or flags):
        log.warning("⚠️  Parse produced 0 results on first attempt — retrying...")
        response = call_llm(prompt)
        if args.verbose:
            log.info("=== RAW LLM OUTPUT (retry) ===")
            log.info("%s", response)
            log.info("==============================")
        counters, synapses, flags = parse_gardener_output(response)

    log.info("📋 Results:")
    log.info("   Counter-leaves: %d", len(counters))
    log.info("   Synapses:       %d", len(synapses))
    log.info("   Flags:          %d", len(flags))

    if not (counters or synapses or flags):
        branch_label = args.branch if args.branch else "all"
        log.warning(
            "⚠️  Gardener parse produced 0 results for branch %s after 2 attempts "
            "— LLM output may be malformed", branch_label
        )
        return

    # Show what we found
    if counters:
        log.info("⚔️  Counter-leaves:")
        for c in counters:
            log.info("[%s] %s", c['branch'], c['content'][:120])

    if synapses:
        log.info("🔗 Synapses:")
        for s in synapses:
            log.info("%s", s['content'][:120])

    if flags:
        log.info("🚩 Flags:")
        for fl in flags:
            log.info("[%s] %s", fl['leaf_id'], fl['reason'])

    # Tiered commit: constitutional branches require human review before commit
    # Operational branches auto-commit — adversarial pressure runs free
    CONSTITUTIONAL_BRANCHES = {"identity", "philosophy", "core"}

    committed_counters = []
    staged_counters = []
    staged_synapses = synapses  # synapses always stage by default

    for c in counters:
        if c["branch"] in CONSTITUTIONAL_BRANCHES:
            staged_counters.append(c)
        else:
            committed_counters.append(c) if not args.dry_run else None

    if staged_counters:
        log.info("📋 Staging %d constitutional counter-leaf(ves) for review:", len(staged_counters))
        for c in staged_counters:
            log.info("[%s] %s", c['branch'], c['content'][:120])

    if not args.dry_run:
        log.info("✍️  Committing operational counter-leaves to knowledge tree...")
        source = f"gardener-{today_local()}"

        committed_written = []
        if committed_counters:
            with tree_lock() as fresh_tree:
                for c in committed_counters:
                    branch = c["branch"]
                    if branch not in fresh_tree["branches"]:
                        log.warning("⚠️  Unknown branch '%s' — skipped", branch)
                        continue

                    # Semantic dedup gate: skip near-duplicate COUNTERs
                    try:
                        is_dup, dup_id, dup_score = is_duplicate_counter(
                            c["content"], fresh_tree
                        )
                        if is_dup:
                            leaf_hash = _kt_hash_leaf(c["content"], branch, now_utc())[:12]
                            log.info(
                                "DEDUP SKIP: [%s] too similar to [%s] (score: %.2f)",
                                leaf_hash, dup_id, dup_score,
                            )
                            continue
                    except Exception as e:
                        leaf_hash = _kt_hash_leaf(c["content"], branch, now_utc())[:12]
                        log.warning(
                            "DEDUP WARNING: embedding unavailable, skipping "
                            "dedup check for [%s]: %s", leaf_hash, e,
                        )

                    leaf_id = add_leaf(fresh_tree, branch, c["content"], source, c["confidence"])
                    log.info("✅ Added counter [%s] to %s", leaf_id, branch)
                    committed_written.append({**c, "leaf_id": leaf_id})

                    try:
                        original_id = c.get("original_leaf_id")
                        if not original_id:
                            # Backward compat: old staged items may still have COUNTER: [id] prefix
                            _orig_match = re.match(r"COUNTER:\s*\[([a-f0-9]+)\]", c["content"])
                            original_id = _orig_match.group(1) if _orig_match else None
                        if original_id and leaf_id:
                            from core.knowledge_synapses import load_synapses as _ls, save_synapses as _ss, add_synapse as _as
                            _synapses = _ls()
                            _as(_synapses, leaf_id, original_id, "CONTRADICTS",
                                note="Gardener counter-challenge", source="gardener")
                            _ss(_synapses)
                            log.info("🔗 Synapse: %s --[CONTRADICTS]--> %s", leaf_id, original_id)
                    except Exception as e:
                        log.warning("Synapse creation failed (non-fatal): %s", e)
            log.info("💾 Tree saved.")
        committed_counters = committed_written

        if staged_synapses or staged_counters:
            total_staged = len(staged_synapses) + len(staged_counters)
            log.info("📋 Staging %d item(s) for review -> %s", total_staged, GARDEN_STAGING)
            log.info("(Run: python3 gardener.py --apply-staging to commit)")
    else:
        committed_counters = []

    write_garden_log(counters, synapses, flags, dry_run=args.dry_run)
    log.info("📝 Log written -> %s", GARDEN_LOG)

    # Write staging file for synapses + constitutional counter-leaves
    if not args.dry_run and (staged_synapses or staged_counters):
        write_staging_file(staged_synapses, flags, staged_counters=staged_counters)

    # Emit ESCALATION_SENT into the events journal when constitutional
    # counter-leaves are staged (action-layer audit trail). Non-fatal:
    # gardener must continue even if the events module is unavailable.
    if staged_counters and not args.dry_run:
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from events import emit_escalation
            evt = emit_escalation(
                agent_id="gardener",
                reason=f"{len(staged_counters)} constitutional counter-leaf(ves) staged for human review — branches: {sorted({c['branch'] for c in staged_counters})}",
                branch="constitutional",
                journal_path=EVENTS_JOURNAL,
            )
            log.info("📋 Escalation emitted: %s", evt["event_id"])
        except Exception as e:
            log.warning("⚠️  events.emit_escalation skipped (non-fatal): %s", e)

    # Write notify flag for session startup
    write_notify_flag(committed_counters, staged_synapses, flags, dry_run=args.dry_run,
                      staged_counters=staged_counters)

    # Telegram notification
    notify_telegram(
        n_counters=len(committed_counters) + len(staged_counters),
        n_synapses=len(staged_synapses),
        n_flags=len(flags),
    )

    # Action layer: record outcome at the end of the main pass.
    # Severity is 0.0 if no operational counters committed (clean run);
    # 0.2 if any were committed (challenges found, not catastrophic).
    if _gardener_action_id and not args.dry_run:
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from action_log import record_outcome
            _severity = 0.0 if not committed_counters else 0.2
            record_outcome(
                action_id=_gardener_action_id,
                outcome_severity=_severity,
                agent_id="gardener",
                description=f"{len(committed_counters)} counter(s) committed, "
                            f"{len(staged_counters)} staged",
                journal_path=os.path.join(BASE_DIR, "data", "action_log.jsonl"),
            )
            log.info("✅ Action outcome recorded (severity=%.1f)", _severity)
        except Exception as e:
            log.warning("⚠️  action_log.record_outcome skipped (non-fatal): %s", e)

    log.info("✅ Gardening complete — %s", now_local())


def notify_telegram(n_counters=0, n_synapses=0, n_flags=0):
    """Send a brief summary to Telegram.  Silently skips if env vars are missing."""
    bot_token = os.environ.get("PCIS_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("PCIS_TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return
    text = f"\U0001f33f Gardener: {n_counters} counters, {n_synapses} synapses, {n_flags} flags"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        log.info("Telegram notification sent.")
    except Exception as e:
        log.warning("Telegram notification failed (non-fatal): %s", e)


if __name__ == "__main__":
    main()


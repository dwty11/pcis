#!/usr/bin/env python3
"""
External LLM Validation — PCIS Demo
Sends high-confidence leaves to the configured LLM for adversarial challenge.
All processing stays within the closed perimeter.

Supported providers (config.json → llm_provider):
  - "anthropic"     — Anthropic Messages API (requires llm_api_key or ANTHROPIC_API_KEY)
  - "openai"        — OpenAI-compatible Chat Completions (requires llm_api_key or OPENAI_API_KEY)
  - "openai_compat" — Any OpenAI-compatible local adapter (requires OPENAI_COMPAT_KEY for health check)
  - "ollama"        — Local Ollama (default, no key required)
"""

import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timezone, timedelta

try:  # keep emoji / box-drawing output alive on a non-UTF-8 console (e.g. RU-Windows cp1251)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_tree import hash_leaf
from root_report import build_root_report, digest_file, root_claim
# compute_root_hash / compute_branch_hash are deliberately NOT imported at
# module scope: they are the wrong tool everywhere except inside
# _merkle_snapshot, and a before/after pair computed with the raw
# compute_root_hash reads STORED branch hashes, which is the defect this
# module already shipped once. Out of scope means a reviewer cannot
# reintroduce it by accident — subtraction rather than a test that the
# mistake was not made.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pcis.adversarial_validator")

# SSL verification — override with PCIS_SSL_VERIFY=false only for self-signed certs
_SSL_VERIFY = os.environ.get("PCIS_SSL_VERIFY", "true").lower() != "false"
_SSL_CONTEXT = None
if not _SSL_VERIFY:
    import ssl as _ssl
    _SSL_CONTEXT = _ssl.create_default_context()
    _SSL_CONTEXT.check_hostname = False
    _SSL_CONTEXT.verify_mode = _ssl.CERT_NONE
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except ImportError:
        pass  # urllib3 not installed; SSL warning suppression unavailable
    warnings.warn(
        "PCIS_SSL_VERIFY=false: SSL certificate verification disabled. Do not use in production.",
        RuntimeWarning,
        stacklevel=1,
    )

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE_FILE = os.path.join(REPO_ROOT, "demo", "demo_tree.json")
OUTPUT_FILE = os.path.join(REPO_ROOT, "demo", "adversarial_validation_run.json")
CONFIG_FILE = os.path.join(REPO_ROOT, "config.json")
TZ_UTC = timezone(timedelta(hours=0))
RUN_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Provider configs
PROVIDER_DEFAULTS = {
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-20250514",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
    },
    "openai_compat": {
        "url": "http://localhost:7860/v1/chat/completions",
        "model": "local-adapter",
        "env_key": "OPENAI_COMPAT_KEY",
    },
    "ollama": {
        "url": "http://localhost:11434/api/chat",
        "model": "qwen3:14b",
        "env_key": None,
    },
}

ADVERSARIAL_PROMPT = (
    "You are a critical analyst reviewing an AI knowledge base entry.\n\n"
    "Entry content: {content}\n"
    "Confidence score: {confidence}\n\n"
    "Your task: Generate a rigorous counter-argument or critical validation of this belief. "
    "Consider:\n"
    "- Is the confidence score justified by the evidence?\n"
    "- What assumptions are being made that could be wrong?\n"
    "- What important counter-arguments or edge cases are missing?\n"
    "- Could this belief become stale or context-dependent?\n\n"
    "Reply with ONE concise paragraph containing your strongest counter-argument "
    "or validation critique. Be specific and adversarial — your job is to find weaknesses, "
    "not to confirm."
)


def _merkle_snapshot(tree):
    """Root derived from LEAF CONTENT, for both ends of a before/after pair.

    INVARIANT(test_stale_branch_hash_alone_does_not_manufacture_a_transition):
    before and after must be measured the same way, or a difference reports
    "we computed it differently" rather than "it changed".

    ``merkle_before`` used to be ``compute_root_hash(tree)`` — which reads the
    tree's STORED branch hashes — while ``merkle_after`` recomputed every branch
    hash from leaf content first. A stale stored branch hash, with no content
    change at all, therefore produced two different values, and this pair is
    written to adversarial_validation_run.json and rendered as a MERKLE ROOT
    TRANSITION. A difference in derivation method, captioned as change over time.

    Works on a deep copy: the validator is documented read-only over the tree
    it is handed.
    """
    from knowledge_tree import compute_branch_hash, compute_root_hash

    snapshot = json.loads(json.dumps(tree))
    for branch in snapshot.get("branches", {}).values():
        branch["hash"] = compute_branch_hash(branch["leaves"])
    return compute_root_hash(snapshot)


def load_config():
    """Load config.json if it exists, return dict."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to read config.json: %s — using defaults", e)
    return {}


class UnknownProviderError(ValueError):
    """config named a provider PROVIDER_DEFAULTS has no entry for.

    Raised, never substituted. On 2026-07-27 this code demoted ``openrouter``
    to ollama behind a log warning, then called ollama with an OpenRouter model
    name; all five calls 404'd and five canned paragraphs were written down as
    adversarial challenges. Each step recorded the previous one's output as
    normal input. A substitution that nothing downstream can see is worse than
    a stop, because the run still produces a plausible artifact.
    """


def get_provider_config(config):
    """Determine provider, model, api_key, and url from config + env."""
    provider = config.get("llm_provider", "ollama")
    if provider not in PROVIDER_DEFAULTS:
        raise UnknownProviderError(
            f"llm_provider {provider!r} is not supported. Known providers: "
            f"{', '.join(sorted(PROVIDER_DEFAULTS))}. Refusing to substitute — "
            "a demoted provider produces a run that looks like it succeeded."
        )

    defaults = PROVIDER_DEFAULTS[provider]
    model = config.get("llm_model", defaults["model"])
    url = config.get("llm_url", defaults["url"])

    # API key: config.json → env var
    api_key = config.get("llm_api_key", "")
    if not api_key and defaults["env_key"]:
        api_key = os.environ.get(defaults["env_key"], "")

    return provider, model, url, api_key


def _call_anthropic(url, api_key, model, prompt, timeout=90):
    """Call Anthropic Messages API."""
    body = json.dumps({
        "model": model,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        result = json.loads(resp.read().decode())
    # Anthropic response: {"content": [{"type": "text", "text": "..."}]}
    return result["content"][0]["text"]


def _call_openai(url, model, prompt, timeout=90, api_key=None):
    """Call OpenAI-compatible Chat Completions API.

    Pass api_key=None for local adapters that handle auth internally
    (e.g. an OpenAI-compatible adapter on localhost:7860 that fronts a
    third-party provider and handles its OAuth flow itself).
    """
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 512,
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        result = json.loads(resp.read().decode())
    return result["choices"][0]["message"]["content"]


def _call_ollama(url, model, prompt, timeout=180):
    """Call Ollama local chat API."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 512},
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        result = json.loads(resp.read().decode())
    return result.get("message", {}).get("content", "").strip()


def send_to_llm(provider, url, api_key, model, leaf_content, leaf_confidence=0.0, retries=2):
    """Send adversarial prompt to the configured LLM with retry + exponential backoff.

    Returns the LLM response text, or raises the last exception after retries exhausted.
    """
    prompt = ADVERSARIAL_PROMPT.format(content=leaf_content, confidence=leaf_confidence)

    dispatch = {
        "anthropic": lambda: _call_anthropic(url, api_key, model, prompt),
        "openai": lambda: _call_openai(url, model, prompt, api_key=api_key),
        "openai_compat": lambda: _call_openai(url, model, prompt),  # adapter handles auth internally
        "ollama": lambda: _call_ollama(url, model, prompt),
    }
    call_fn = dispatch.get(provider)
    if call_fn is None:
        raise ValueError(f"Unknown provider: {provider}")

    last_err = None
    for attempt in range(retries + 1):
        try:
            return call_fn()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            # Don't retry auth/permission failures — they won't resolve on retry
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                raise
            last_err = e
            if attempt < retries:
                backoff = 2 ** attempt  # 1s, 2s
                log.warning("LLM call attempt %d failed (%s) — retrying in %ds",
                            attempt + 1, e, backoff)
                time.sleep(backoff)
            continue
    raise last_err


# There is deliberately no FALLBACK_CHALLENGES table here.
#
# It held five pre-written paragraphs keyed by branch, with an unkeyed branch
# defaulting to the "compliance" text. On 2026-07-27 that produced five
# "challenges" of which four were the same paragraph, each committed as a leaf
# carrying source="adversarial-<date>" and confidence=0.65 — the values a real
# challenge carries. The canned text was not the defect; the defect was that it
# reached a leaf wearing a real challenge's clothes.
#
# Removed rather than flagged: a hedge path that still writes a leaf is one
# forgotten field away from being indistinguishable again.

# outcome vocabulary — the summary is derived from this set, never accumulated
ATTEMPT_OUTCOMES = ("live", "failed")

PRODUCED_BY_LIVE = "live-llm"


def challenge_leaves(selected, challenge_fn, model):
    """Challenge each selected leaf, returning (counters, attempts).

    ``challenge_fn(content, confidence) -> str`` raises on failure.

    A failed call yields **no counter leaf** — a COUNTER built from anything
    other than a real challenge is a templated response, not an adversarial
    pass. The failure is still recorded in ``attempts``: refusing to commit
    must not also erase the evidence that a call was made and did not answer.

    CAPTION PROVENANCE: every field on a returned counter is derived from this
    call — ``produced_by`` from the branch that built it, ``model`` from the
    argument naming what actually answered. Nothing here reads config.
    """
    counters, attempts = [], []

    for branch_name, leaf in selected:
        attempt = {"leaf_id": leaf["id"], "branch": branch_name, "model": model}
        try:
            response = challenge_fn(leaf["content"], leaf.get("confidence", 0.0))
        except Exception as e:  # noqa: BLE001 — any transport failure is a failure
            log.error("challenge failed for leaf %s: %s", leaf["id"], e)
            attempts.append({**attempt, "outcome": "failed", "error": str(e)})
            continue

        if not response or not response.strip():
            attempts.append({**attempt, "outcome": "failed",
                             "error": "empty response"})
            continue

        now = datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        content = f"COUNTER: [{leaf['id']}] {response.strip()}"
        content_hash = hash_leaf(content, branch_name, now)

        counters.append({
            "id": content_hash[:12],
            "hash": content_hash,
            "content": content,
            "produced_by": PRODUCED_BY_LIVE,
            "source": f"adversarial-{RUN_DATE}-{PRODUCED_BY_LIVE}",
            "model": model,
            "confidence": 0.65,
            "created": now,
            "promoted_to": None,
            "challenged_id": leaf["id"],
            "branch": branch_name,
        })
        attempts.append({**attempt, "outcome": "live", "error": None})

    return counters, attempts


def summarize_attempts(attempts):
    """Derive the headline from the set of outcomes, never by accumulation.

    A boolean accumulated across branches has to remember to flip in each
    failing one; a count derived from the set cannot forget a branch. An
    outcome outside ATTEMPT_OUTCOMES raises rather than being silently dropped
    into neither bucket.
    """
    unknown = {a["outcome"] for a in attempts} - set(ATTEMPT_OUTCOMES)
    if unknown:
        raise ValueError(f"unclassified attempt outcome(s): {sorted(unknown)}")

    return {
        "attempted": len(attempts),
        "live": sum(1 for a in attempts if a["outcome"] == "live"),
        "failed": sum(1 for a in attempts if a["outcome"] == "failed"),
    }


# Keep legacy interface for backwards compatibility
def load_key():
    """Load API key from config.json or environment."""
    config = load_config()
    provider, _, _, api_key = get_provider_config(config)
    if api_key:
        return api_key
    # Fallback: try env vars directly
    for env_var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(env_var, "")
        if val:
            return val
    return ""


def get_access_token(api_key):
    """Legacy stub — real providers use API keys directly, not OAuth tokens.
    Returns the api_key as-is for backwards compatibility."""
    return api_key


def select_leaves(tree):
    """Select 5 high-confidence leaves (>=0.75) from different branches."""
    candidates = []
    for branch_name, branch in tree["branches"].items():
        best = None
        for leaf in branch["leaves"]:
            if leaf["content"].startswith("COUNTER:"):
                continue
            if leaf["confidence"] >= 0.75:
                if best is None or leaf["confidence"] > best[1]["confidence"]:
                    best = (branch_name, leaf)
        if best:
            candidates.append(best)

    # Sort by confidence descending, take top 5
    candidates.sort(key=lambda x: x[1]["confidence"], reverse=True)
    return candidates[:5]


def main():
    config = load_config()
    provider, model, url, api_key = get_provider_config(config)

    print("=" * 60)
    print("  External LLM Validation — PCIS")
    print(f"  Provider: {provider}  |  Model: {model}  |  Date: {RUN_DATE}")
    print("=" * 60)
    print()

    # Digest the tree BEFORE anything runs, so whether it was written is an
    # observation rather than this function's opinion of itself.
    tree_digest_before = digest_file(TREE_FILE)

    with open(TREE_FILE, "r", encoding="utf-8") as f:
        tree = json.load(f)

    merkle_before = _merkle_snapshot(tree)
    print(f"  Merkle root (before): {merkle_before[:24]}...")

    # Select leaves
    selected = select_leaves(tree)
    print(f"  Selected {len(selected)} leaves from branches: {', '.join(s[0] for s in selected)}")
    print()

    if provider != "ollama" and not api_key:
        env_name = PROVIDER_DEFAULTS[provider]["env_key"]
        print(f"  No API key found (config.json or ${env_name}) — every call "
              "will fail and be recorded as such.\n")
    else:
        print(f"  Challenging via {provider} ({model}).\n")

    def _challenge(content, confidence):
        return send_to_llm(provider, url, api_key, model, content, confidence)

    counters, attempts = challenge_leaves(selected, _challenge, model)
    summary = summarize_attempts(attempts)

    for a in attempts:
        if a["outcome"] == "live":
            print(f"  [{a['branch']}] leaf {a['leaf_id']}: challenged")
        else:
            print(f"  [{a['branch']}] leaf {a['leaf_id']}: NO CHALLENGE — {a['error']}")
    print()
    print(f"  {summary['live']}/{summary['attempted']} leaves challenged"
          + (f", {summary['failed']} failed" if summary["failed"] else ""))
    print()

    # demo_tree.json is NEVER written — the demo tree is a curated static
    # showcase. So this root is a PROJECTION: what the tree would hash to if
    # these counters were committed. Computed on a copy, because a value
    # describing a post-state must not be bought by mutating the input.
    #
    # It is handed to build_root_report, which decides what to CALL it by
    # re-reading the file: an after-root is emitted only if the bytes changed.
    # The previous version of this comment claimed a `tree_written` flag "tells
    # a consumer this is a projection" — no consumer read it, and the dashboard
    # rendered the projection as a root transition. Naming the field correctly
    # is the fix; a flag nothing reads is not.
    projected = json.loads(json.dumps(tree))
    for c in counters:
        projected["branches"][c["branch"]]["leaves"].append({
            "id": c["id"], "hash": c["hash"], "content": c["content"],
            "source": c["source"], "confidence": c["confidence"],
            "created": c["created"], "promoted_to": None,
        })
    merkle_after = _merkle_snapshot(projected)
    print(f"  Merkle root (before):    {merkle_before[:24]}...")
    print(f"  Merkle root (projected): {merkle_after[:24]}...")
    print("  demo_tree.json unchanged (read-only for validator)")

    # Save validation run
    run_data = {
        "run_date": RUN_DATE,
        "provider": provider,
        "model": model,
        # CAPTION PROVENANCE: derived from the attempt set, not from len(selected).
        # This counted committed counters before, which happened to be right;
        # deriving it from `summary` keeps it right if the leaf path changes.
        "entries_challenged": summary["live"],
        "summary": summary,
        "attempts": attempts,
        "counters": counters,
    }
    run_data.update(build_root_report(
        root_before=merkle_before,
        root_projected=merkle_after,
        tree_path=TREE_FILE,
        digest_before=tree_digest_before,
    ))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(run_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved {OUTPUT_FILE}")

    print()
    print("─" * 60)
    # CAPTION PROVENANCE: both numbers from `summary`, which is derived from
    # the attempt set. The old line read "N adversarial challenges generated"
    # off len(counters) with no mention of failures, so a run where every call
    # 404'd printed the same shape as a clean one.
    print(f"  COMPLETE: {summary['live']}/{summary['attempted']} leaves challenged"
          + (f" · {summary['failed']} FAILED, no leaf built" if summary["failed"] else ""))
    # CAPTION PROVENANCE: reads run_data, so the console cannot say something
    # the artifact does not. This line and the field name drifted apart once.
    _rc = root_claim(run_data)
    if _rc["kind"] == "projected":
        print(f"  Merkle root: {_rc['before'][:16]}... (tree not written; "
              f"would be {_rc['projected'][:16]}... if committed)")
    elif _rc["kind"] == "transition":
        print(f"  Merkle root: {_rc['before'][:16]}... → {_rc['after'][:16]}...")
    else:
        print(f"  Merkle root: {merkle_before[:16]}... (unchanged)")
    print(f"  Output: adversarial_validation_run.json")
    print("─" * 60)


if __name__ == "__main__":
    main()

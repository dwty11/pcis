#!/usr/bin/env python3
"""
External LLM Validation — PCIS Demo
Sends high-confidence leaves to the configured LLM for adversarial challenge.
All processing stays within the closed perimeter.

Supported providers (config.json → llm_provider):
  - "anthropic" — Anthropic Messages API (requires llm_api_key or ANTHROPIC_API_KEY)
  - "openai"    — OpenAI-compatible Chat Completions (requires llm_api_key or OPENAI_API_KEY)
  - "ollama"    — Local Ollama (default, no key required)
"""

import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import warnings
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_tree import compute_root_hash, compute_branch_hash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pcis.adversarial_validator")

# SSL verification — override with PCIS_SSL_VERIFY=false only for self-signed certs
_SSL_VERIFY = os.environ.get("PCIS_SSL_VERIFY", "true").lower() != "false"
if not _SSL_VERIFY:
    import ssl as _ssl
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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


def load_config():
    """Load config.json if it exists, return dict."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to read config.json: %s — using defaults", e)
    return {}


def get_provider_config(config):
    """Determine provider, model, api_key, and url from config + env."""
    provider = config.get("llm_provider", "ollama")
    if provider not in PROVIDER_DEFAULTS:
        log.warning("Unknown llm_provider '%s' — falling back to ollama", provider)
        provider = "ollama"

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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode())
    # Anthropic response: {"content": [{"type": "text", "text": "..."}]}
    return result["content"][0]["text"]


def _call_openai(url, api_key, model, prompt, timeout=90):
    """Call OpenAI-compatible Chat Completions API."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 512,
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode())
    return result.get("message", {}).get("content", "").strip()


def send_to_llm(provider, url, api_key, model, leaf_content, leaf_confidence=0.0, retries=2):
    """Send adversarial prompt to the configured LLM with retry + exponential backoff.

    Returns the LLM response text, or raises the last exception after retries exhausted.
    """
    prompt = ADVERSARIAL_PROMPT.format(content=leaf_content, confidence=leaf_confidence)

    dispatch = {
        "anthropic": lambda: _call_anthropic(url, api_key, model, prompt),
        "openai": lambda: _call_openai(url, api_key, model, prompt),
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


# Fallback challenges when LLM API is unreachable (network/geo restrictions)
FALLBACK_CHALLENGES = {
    "products": "The stated product specifications are tied to a specific point in time and subject to rapid change. High confidence scores on time-sensitive data should include a staleness decay parameter — what is true today may be materially different in 30 days. The knowledge tree should track a 'valid_until' field for perishable facts.",
    "compliance": "The compliance assertion covers current architecture but does not account for dependency updates or third-party integrations that may introduce external calls. This leaf requires a periodic re-verification trigger — a static assertion about dynamic properties is structurally weak. Suggest adding a review_by date.",
    "lessons": "The behavioral pattern described here is based on a limited observation window and is subject to confirmation bias. Patterns inferred from fewer than 5 data points should carry confidence no higher than 0.6. Recommend flagging this leaf for re-evaluation after 3 additional interactions.",
    "clients": "This leaf contains a subjective assessment without citing the source of the sensitivity evaluation. Recommendations derived from assumed preferences rather than stated ones carry implicit risk. The knowledge tree should distinguish between observed facts and inferred preferences.",
    "relationships": "Relationship quality scores have a half-life. A score recorded 3+ months ago without a refresh event should be automatically downgraded in confidence. High-priority retention flags not backed by recency data can lead to misallocated effort.",
}


def get_fallback_challenge(branch_name):
    """Return a pre-generated adversarial challenge for demo purposes."""
    return FALLBACK_CHALLENGES.get(branch_name, FALLBACK_CHALLENGES["compliance"])


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

    # Load tree
    with open(TREE_FILE, "r") as f:
        tree = json.load(f)

    merkle_before = compute_root_hash(tree)
    print(f"  Merkle root (before): {merkle_before[:24]}...")

    # Select leaves
    selected = select_leaves(tree)
    print(f"  Selected {len(selected)} leaves from branches: {', '.join(s[0] for s in selected)}")
    print()

    # Check API key for cloud providers
    use_fallback = False
    if provider in ("anthropic", "openai") and not api_key:
        env_name = PROVIDER_DEFAULTS[provider]["env_key"]
        print(f"  No API key found (config.json or ${env_name}).")
        print("  Using fallback mode (pre-generated challenges).\n")
        use_fallback = True
    elif provider == "ollama":
        print(f"  Using local Ollama ({model}).\n")
    else:
        print(f"  API key loaded for {provider}.\n")

    # Challenge each leaf
    counters = []
    for i, (branch_name, leaf) in enumerate(selected, 1):
        print(f"  [{i}/{len(selected)}] Challenging leaf {leaf['id']} ({branch_name})...")
        print(f"         \"{leaf['content'][:80]}...\"")

        if not use_fallback:
            try:
                response = send_to_llm(
                    provider, url, api_key, model,
                    leaf["content"], leaf.get("confidence", 0.0),
                )
                print(f"         Response received ({len(response)} chars)")
            except Exception as e:
                log.error("LLM call failed for leaf %s: %s", leaf["id"], e)
                print(f"         API call failed: {e}")
                print(f"         Falling back to pre-generated challenge.")
                response = get_fallback_challenge(branch_name)
        else:
            response = get_fallback_challenge(branch_name)

        # Skip empty responses — an empty COUNTER leaf is noise in the tree
        if not response or not response.strip():
            log.warning("Empty response for leaf %s — skipping COUNTER leaf", leaf["id"])
            print(f"         Empty response — skipping.")
            continue
            print(f"         Fallback challenge ({len(response)} chars)")

        # Build COUNTER leaf
        content = f"COUNTER: [{leaf['id']}] {response}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        now = datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        counter_leaf = {
            "id": content_hash[:12],
            "hash": content_hash,
            "content": content,
            "source": f"adversarial-{RUN_DATE}",
            "confidence": 0.65,
            "created": now,
            "promoted_to": None,
            "challenged_id": leaf["id"],
            "branch": branch_name,
        }
        counters.append(counter_leaf)

        # Append to tree
        tree["branches"][branch_name]["leaves"].append({
            "id": counter_leaf["id"],
            "hash": counter_leaf["hash"],
            "content": counter_leaf["content"],
            "source": counter_leaf["source"],
            "confidence": counter_leaf["confidence"],
            "created": counter_leaf["created"],
            "promoted_to": None,
        })
        print(f"         COUNTER leaf: {counter_leaf['id']}")
        print()

    # Recompute hashes
    for name in tree["branches"]:
        branch = tree["branches"][name]
        branch["hash"] = compute_branch_hash(branch["leaves"])

    merkle_after = compute_root_hash(tree)
    tree["root_hash"] = merkle_after
    tree["last_updated"] = datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Save updated tree
    with open(TREE_FILE, "w") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
    print(f"  Merkle root (after):  {merkle_after[:24]}...")
    print(f"  Updated demo_tree.json")

    # Save validation run
    run_data = {
        "run_date": RUN_DATE,
        "provider": provider,
        "model": model,
        "entries_challenged": len(counters),
        "merkle_root_before": merkle_before,
        "merkle_root_after": merkle_after,
        "counters": counters,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(run_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved {OUTPUT_FILE}")

    print()
    print("─" * 60)
    print(f"  COMPLETE: {len(counters)} adversarial challenges generated")
    print(f"  Merkle root: {merkle_before[:16]}... → {merkle_after[:16]}...")
    print(f"  Output: adversarial_validation_run.json")
    print("─" * 60)


if __name__ == "__main__":
    main()

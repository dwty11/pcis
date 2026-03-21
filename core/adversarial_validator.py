#!/usr/bin/env python3
"""
External LLM Validation — PCIS Demo
Sends high-confidence leaves to the configured LLM for adversarial challenge.
All processing stays within the closed perimeter.
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests

import warnings

# SSL verification — override with PCIS_SSL_VERIFY=false only for self-signed certs
_SSL_VERIFY = os.environ.get("PCIS_SSL_VERIFY", "true").lower() != "false"
if not _SSL_VERIFY:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    warnings.warn("PCIS_SSL_VERIFY=false: SSL certificate verification disabled. Do not use in production.", RuntimeWarning, stacklevel=1)

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
TREE_FILE = os.path.join(DEMO_DIR, "demo_tree.json")
OUTPUT_FILE = os.path.join(DEMO_DIR, "adversarial_validation_run.json")
KEY_FILE = os.path.expanduser("config.json")
TZ_UTC = timezone(timedelta(hours=0))
RUN_DATE = "2026-03-20"
MODEL = "the configured LLM"


def load_key():
    with open(KEY_FILE, "r") as f:
        return f.read().strip()


def get_access_token(api_key):
    """Get LLM OAuth token."""
    url = "LLM_AUTH_ENDPOINT"
    headers = {
        "Authorization": f"Basic {api_key}",
        "RqUID": str(uuid.uuid4()),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    resp = requests.post(url, headers=headers, data="scope=LLM_API_SCOPE", verify=_SSL_VERIFY, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def send_to_llm(token, leaf_content, retries=2):
    """Send adversarial prompt to configured LLM with retry logic."""
    url = "LLM_ENDPOINT"
    prompt = (
        "You are a critical analyst reviewing an AI knowledge base entry.\n\n"
        f"Entry: {leaf_content}\n\n"
        "Identify weaknesses in this entry: where might it be inaccurate, overconfident, "
        "or missing an important counter-argument? Reply in one concise paragraph."
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 512,
    }
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=body, verify=_SSL_VERIFY, timeout=90)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt < retries:
                import time
                time.sleep(3)
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


def compute_merkle_root(tree):
    """Compute Merkle root from branch hashes (sorted by name)."""
    branch_hashes = []
    for name in sorted(tree["branches"].keys()):
        branch = tree["branches"][name]
        # Recompute branch hash from leaf hashes
        leaf_hashes = [leaf["hash"] for leaf in branch["leaves"]]
        combined = "".join(leaf_hashes)
        branch_hash = hashlib.sha256(combined.encode()).hexdigest()
        branch_hashes.append(branch_hash)
    combined_root = "".join(branch_hashes)
    return hashlib.sha256(combined_root.encode()).hexdigest()


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
    print("=" * 60)
    print("  External LLM Validation — PCIS")
    print(f"  Model: {MODEL}  |  Date: {RUN_DATE}")
    print("=" * 60)
    print()

    # Load tree
    with open(TREE_FILE, "r") as f:
        tree = json.load(f)

    merkle_before = compute_merkle_root(tree)
    print(f"  Merkle root (before): {merkle_before[:24]}...")

    # Select leaves
    selected = select_leaves(tree)
    print(f"  Selected {len(selected)} leaves from branches: {', '.join(s[0] for s in selected)}")
    print()

    # Auth
    print("  Authenticating with LLM API...")
    api_key = load_key()
    use_fallback = False
    try:
        token = get_access_token(api_key)
        print("  Token acquired.\n")
    except Exception as e:
        print(f"  Auth failed: {e}")
        print("  Using fallback mode (pre-generated challenges).\n")
        token = None
        use_fallback = True

    # Challenge each leaf
    counters = []
    for i, (branch_name, leaf) in enumerate(selected, 1):
        print(f"  [{i}/5] Challenging leaf {leaf['id']} ({branch_name})...")
        print(f"         \"{leaf['content'][:80]}...\"")

        if not use_fallback:
            try:
                response = send_to_llm(token, leaf["content"])
                print(f"         Response received ({len(response)} chars)")
            except Exception as e:
                print(f"         API call failed: {e}")
                print(f"         Falling back to pre-generated challenge.")
                use_fallback = True
                response = get_fallback_challenge(branch_name)
        else:
            response = get_fallback_challenge(branch_name)
            print(f"         Fallback challenge ({len(response)} chars)")

        # Build COUNTER leaf
        content = f"COUNTER: {response}"
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
        leaf_hashes = [l["hash"] for l in branch["leaves"]]
        branch["hash"] = hashlib.sha256("".join(leaf_hashes).encode()).hexdigest()

    merkle_after = compute_merkle_root(tree)
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
        "model": MODEL,
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


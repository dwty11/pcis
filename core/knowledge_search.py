#!/usr/bin/env python3
"""
knowledge_search.py — Semantic Search Over the Knowledge Tree

Searches the knowledge tree by MEANING, not just keywords.
Uses a local embedding model via Ollama -- free, private, no vendor lock-in.

Usage:
    python3 knowledge_search.py "what did I learn about identity?"
    python3 knowledge_search.py "cost lessons" --top 5
    python3 knowledge_search.py "architectural decisions" --branch technical
    python3 knowledge_search.py --reindex              # rebuild all embeddings
    python3 knowledge_search.py --stats                 # show index stats
    python3 knowledge_search.py --model nomic-embed-text  # change embedding model

Setup (one time):
    ollama pull nomic-embed-text
    python3 knowledge_search.py --reindex

How it works:
    1. Every knowledge leaf gets embedded into a vector (768 dimensions)
    2. Vectors stored in a local JSON file alongside the tree
    3. When you search, your query gets embedded and compared to all leaves
    4. Results ranked by cosine similarity -- meaning, not keywords
    5. All local. All free. All portable.

Embedding model: nomic-embed-text (default)
    - 768 dimensions, 8192 token context
    - Best quality/size ratio for local use
    - Runs on Ollama, no API keys needed
    - Swap to any Ollama embedding model without rewriting code

No external dependencies beyond Ollama. Python 3.8+ only.
"""

import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# --- Configuration -------------------------------------------------------

BASE_DIR = os.environ.get("PCIS_BASE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TREE_FILE = os.path.join(BASE_DIR, "data", "tree.json")
INDEX_FILE = os.path.join(BASE_DIR, "data", "search-index.json")

# Default embedding model -- pull with: ollama pull nomic-embed-text
EMBED_MODEL = os.environ.get("PCIS_EMBED_MODEL", "nomic-embed-text")

# Ollama base URL — override for Docker/remote setups (e.g. http://ollama:11434)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

TZ_UTC = timezone.utc


# --- Ollama Embeddings ---------------------------------------------------

def _ollama_post(path, payload, timeout=30):
    """POST JSON to Ollama and return parsed response, or None on error."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"  Ollama connection error: {e}")
        return None
    except json.JSONDecodeError:
        print("  Invalid JSON from Ollama.")
        return None


def _ollama_get(path, timeout=5):
    """GET JSON from Ollama and return parsed response, or None on error."""
    req = urllib.request.Request(f"{OLLAMA_HOST}{path}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def get_embedding(text, model=None):
    """Get embedding vector from local Ollama. Returns list of floats."""
    model = model or EMBED_MODEL
    response = _ollama_post("/api/embeddings", {"model": model, "prompt": text}, timeout=30)
    if response is None:
        return None
    if "embedding" in response:
        return response["embedding"]
    print(f"  No embedding in response: {list(response.keys())}")
    return None


def check_model_available(model=None):
    """Check if the embedding model is pulled in Ollama."""
    model = model or EMBED_MODEL
    data = _ollama_get("/api/tags", timeout=5)
    if data is None:
        return False
    models = [m.get("name", "") for m in data.get("models", [])]
    return any(model in m for m in models)


# --- Vector Operations ---------------------------------------------------

def cosine_similarity(vec_a, vec_b):
    """Cosine similarity between two vectors. Returns -1 to 1."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = math.sqrt(sum(a * a for a in vec_a))
    magnitude_b = math.sqrt(sum(b * b for b in vec_b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


# --- Index Management ----------------------------------------------------

def load_index():
    """Load the search index from disk."""
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: search index corrupted ({e}). Run --reindex to rebuild.")
                return {
                    "model": EMBED_MODEL,
                    "dimensions": 0,
                    "created": "",
                    "last_reindex": "",
                    "leaf_count": 0,
                    "embeddings": {}
                }
    return {
        "model": EMBED_MODEL,
        "dimensions": 0,
        "created": "",
        "last_reindex": "",
        "leaf_count": 0,
        "embeddings": {}
    }


def save_index(index):
    """Save the search index to disk."""
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f)


def load_tree():
    """Load the knowledge tree."""
    if not os.path.exists(TREE_FILE):
        print("Knowledge tree not found. Run knowledge_tree.py first.")
        sys.exit(1)

    with open(TREE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: knowledge tree is corrupted ({e}). Fix {TREE_FILE} manually.")
            sys.exit(1)


def reindex(model=None):
    """Rebuild the entire search index. Run after adding many leaves."""
    model = model or EMBED_MODEL
    now = datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"Reindexing knowledge tree with {model}...")

    if not check_model_available(model):
        print(f"\n  Model '{model}' not found in Ollama.")
        print(f"  Pull it first: ollama pull {model}")
        sys.exit(1)

    tree = load_tree()
    index = {
        "model": model,
        "dimensions": 0,
        "created": now,
        "last_reindex": now,
        "leaf_count": 0,
        "embeddings": {}
    }

    total_leaves = 0
    indexed = 0

    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            total_leaves += 1

            embed_text = f"[{branch_name}] {leaf['content']}"
            if leaf.get("source"):
                embed_text += f" (source: {leaf['source']})"

            print(f"  Embedding [{branch_name}] {leaf['content'][:50]}...")

            vec = get_embedding(embed_text, model)
            if vec:
                index["embeddings"][leaf["id"]] = {
                    "branch": branch_name,
                    "content": leaf["content"],
                    "source": leaf.get("source", ""),
                    "confidence": leaf.get("confidence", 0.7),
                    "created": leaf.get("created", ""),
                    "vector": vec,
                }
                if index["dimensions"] == 0:
                    index["dimensions"] = len(vec)
                indexed += 1
            else:
                print(f"    Failed to embed leaf {leaf['id']}")

    index["leaf_count"] = indexed

    save_index(index)

    print(f"\nDone. {indexed}/{total_leaves} leaves indexed.")
    print(f"Model: {model} ({index['dimensions']} dimensions)")
    print(f"Index saved to {INDEX_FILE}")


def incremental_index(leaf_id, branch_name, content, source="", confidence=0.7):
    """Index a single new leaf without rebuilding everything."""
    index = load_index()

    if index["model"] != EMBED_MODEL and index["leaf_count"] > 0:
        print(f"  Warning: index uses {index['model']}, current model is {EMBED_MODEL}")
        print(f"  Run --reindex to rebuild with the current model.")
        return False

    embed_text = f"[{branch_name}] {content}"
    if source:
        embed_text += f" (source: {source})"

    vec = get_embedding(embed_text)
    if not vec:
        return False

    index["embeddings"][leaf_id] = {
        "branch": branch_name,
        "content": content,
        "source": source,
        "confidence": confidence,
        "created": datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "vector": vec,
    }
    index["leaf_count"] = len(index["embeddings"])

    if index["dimensions"] == 0:
        index["dimensions"] = len(vec)

    save_index(index)
    return True


# --- Search ---------------------------------------------------------------

def search(query, top_k=3, branch_filter=None, min_confidence=0.0, min_score=0.4):
    """
    Search the knowledge tree by meaning.

    Returns list of (similarity_score, leaf_data) tuples.
    """
    index = load_index()

    if not index["embeddings"]:
        print("Search index is empty. Run: python3 knowledge_search.py --reindex")
        return []

    query_vec = get_embedding(query)
    if not query_vec:
        print("Failed to embed query. Is Ollama running?")
        return []

    results = []
    for leaf_id, leaf_data in index["embeddings"].items():
        if branch_filter and leaf_data["branch"] != branch_filter:
            continue
        if leaf_data.get("confidence", 0) < min_confidence:
            continue

        similarity = cosine_similarity(query_vec, leaf_data["vector"])
        results.append((similarity, leaf_id, leaf_data))

    results.sort(key=lambda x: x[0], reverse=True)

    results = [(s, lid, ld) for s, lid, ld in results if s >= min_score]

    return results[:top_k]


# --- CLI Commands ---------------------------------------------------------

def cmd_search(args):
    """Search the knowledge tree."""
    if not args:
        print("Usage: knowledge_search.py <query> [--top N] [--branch NAME] [--min-confidence 0.N]")
        sys.exit(1)

    query_parts = []
    top_k = 3
    branch_filter = None
    min_confidence = 0.0

    i = 0
    while i < len(args):
        if args[i] == "--top" and i + 1 < len(args):
            top_k = int(args[i + 1])
            i += 2
        elif args[i] == "--branch" and i + 1 < len(args):
            branch_filter = args[i + 1]
            i += 2
        elif args[i] == "--min-confidence" and i + 1 < len(args):
            min_confidence = float(args[i + 1])
            i += 2
        else:
            query_parts.append(args[i])
            i += 1

    query = " ".join(query_parts)

    if not query:
        print("No query provided.")
        sys.exit(1)

    results = search(query, top_k, branch_filter, min_confidence)

    if not results:
        print(f"No results for: {query}")
        return

    print(f"\nSearch: \"{query}\"")
    if branch_filter:
        print(f"Branch: {branch_filter}")
    print(f"Top {len(results)} results:\n")

    for rank, (score, leaf_id, leaf_data) in enumerate(results, 1):
        conf = leaf_data.get("confidence", 0)
        branch = leaf_data.get("branch", "?")
        content = leaf_data.get("content", "")
        source = leaf_data.get("source", "")
        created = leaf_data.get("created", "")

        bar_len = int(score * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)

        print(f"  {rank}. [{bar}] {score:.3f}")
        print(f"     [{branch}] {content}")
        print(f"     source: {source} | confidence: {conf} | created: {created}")
        print(f"     id: {leaf_id}")
        print()


def cmd_stats():
    """Show index statistics."""
    index = load_index()

    if not index["embeddings"]:
        print("Index is empty. Run --reindex first.")
        return

    print(f"\nKnowledge Search Index")
    print(f"  Model:        {index.get('model', '?')}")
    print(f"  Dimensions:   {index.get('dimensions', '?')}")
    print(f"  Leaves:       {index.get('leaf_count', 0)}")
    print(f"  Last reindex: {index.get('last_reindex', '?')}")
    print(f"  Index file:   {INDEX_FILE}")

    branch_counts = {}
    for leaf_data in index["embeddings"].values():
        branch = leaf_data.get("branch", "unknown")
        branch_counts[branch] = branch_counts.get(branch, 0) + 1

    print(f"\n  By branch:")
    for branch in sorted(branch_counts.keys()):
        print(f"    {branch:20s}  {branch_counts[branch]:3d} leaves")

    size_bytes = os.path.getsize(INDEX_FILE) if os.path.exists(INDEX_FILE) else 0
    size_mb = size_bytes / (1024 * 1024)
    print(f"\n  Index size: {size_mb:.1f} MB")


def cmd_reindex(args):
    """Rebuild the index."""
    model = EMBED_MODEL
    for i, arg in enumerate(args):
        if arg == "--model" and i + 1 < len(args):
            model = args[i + 1]
    reindex(model)


# --- Integration Helper ---------------------------------------------------

def search_for_briefing(query, top_k=5):
    """
    Called by external tools to get relevant knowledge for a session briefing.
    Returns formatted text ready to inject into a briefing document.
    """
    results = search(query, top_k)

    if not results:
        return ""

    lines = ["## Relevant Knowledge (semantic search)"]
    for score, leaf_id, leaf_data in results:
        if score < 0.5:
            continue
        branch = leaf_data.get("branch", "?")
        content = leaf_data.get("content", "")
        conf = leaf_data.get("confidence", 0)
        source = leaf_data.get("source", "")
        lines.append(
            f"- [{branch}] {content} "
            f"(relevance: {score:.2f}, confidence: {conf}, source: {source})"
        )

    if len(lines) == 1:
        return ""

    return "\n".join(lines)


# --- Entry Point -----------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    elif args[0] == "--reindex":
        cmd_reindex(args[1:])
    elif args[0] == "--stats":
        cmd_stats()
    else:
        cmd_search(args)

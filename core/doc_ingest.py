#!/usr/bin/env python3
"""
doc_ingest.py — Document Ingestion Pipeline for PCIS

Accepts a text file, PDF path, or raw text content, extracts factual claims
via LLM, and commits each claim as a leaf in the knowledge tree.

Usage:
    python3 -m core.doc_ingest path/to/document.txt
    python3 -m core.doc_ingest path/to/document.pdf

Requires: Ollama running with qwen3:14b (or compatible model).
"""

import json
import os
import sys

# LLM config — Ollama OpenAI-compatible endpoint
LLM_BASE_URL = os.environ.get("PCIS_LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("PCIS_LLM_MODEL", "qwen3:14b")

INGEST_BRANCH = "ingested"
DEFAULT_CONFIDENCE = 0.85

EXTRACTION_PROMPT = """You are a factual claim extractor. Given the following document, extract 10-20 distinct factual claims. Each claim should be a single, self-contained sentence that states one fact, rule, or requirement from the document.

Rules:
- Each claim must stand alone without context
- Be precise and specific — include numbers, dates, names where present
- Do not include opinions or vague statements
- Do not duplicate claims
- Return ONLY a JSON array of strings, no other text

Document:
---
{content}
---

Return a JSON array of 10-20 factual claim strings."""


def extract_claims_from_text(content, llm_base_url=None, llm_model=None):
    """Call LLM to extract factual claims from document text.

    Returns a list of claim strings.
    """
    import urllib.request

    base_url = (llm_base_url or LLM_BASE_URL).rstrip("/")
    model = llm_model or LLM_MODEL

    prompt = EXTRACTION_PROMPT.format(content=content[:8000])

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    reply = data["choices"][0]["message"]["content"]

    # Parse JSON array from the response — handle markdown code fences
    text = reply.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` wrapper
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    claims = json.loads(text)
    if not isinstance(claims, list):
        raise ValueError("LLM did not return a JSON array")

    return [str(c).strip() for c in claims if str(c).strip()]


def read_document(path):
    """Read a text file or PDF and return its text content."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Document not found: {path}")

    if path.lower().endswith(".pdf"):
        return _read_pdf(path)

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_pdf(path):
    """Extract text from a PDF file. Tries pdftotext (poppler), then PyPDF2."""
    import subprocess
    try:
        result = subprocess.run(
            ["pdftotext", path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        pass

    try:
        import PyPDF2
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
    except ImportError:
        pass

    raise RuntimeError(
        f"Cannot read PDF: install pdftotext (poppler-utils) or PyPDF2"
    )


def ingest_document(content, source="manual", tree=None, save=True,
                    tree_path=None, llm_base_url=None, llm_model=None):
    """Full ingestion pipeline: extract claims → commit leaves → return summary.

    Args:
        content: Raw document text.
        source: Source label for provenance.
        tree: Pre-loaded tree dict (if None, loads from disk).
        save: Whether to save the tree to disk after ingestion.
        tree_path: Path to tree file (uses default if None).
        llm_base_url: Override LLM endpoint.
        llm_model: Override LLM model name.

    Returns:
        dict with keys: leaves (list of {id, content, confidence}), count, root_hash, source
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from core.knowledge_tree import (
        add_knowledge, load_tree, save_tree, compute_root_hash,
    )

    claims = extract_claims_from_text(
        content, llm_base_url=llm_base_url, llm_model=llm_model,
    )

    if tree is None:
        tree = load_tree(tree_path)

    leaves = []
    for claim in claims:
        leaf_id = add_knowledge(
            tree, INGEST_BRANCH, claim,
            source=source, confidence=DEFAULT_CONFIDENCE,
        )
        leaves.append({
            "id": leaf_id,
            "content": claim,
            "confidence": DEFAULT_CONFIDENCE,
        })

    root_hash = compute_root_hash(tree)

    if save:
        save_tree(tree, tree_path)

    return {
        "leaves": leaves,
        "count": len(leaves),
        "root_hash": root_hash,
        "source": source,
    }


def ingest_file(path, tree_path=None, llm_base_url=None, llm_model=None):
    """Convenience: read file + ingest. Returns summary dict."""
    content = read_document(path)
    source = os.path.basename(path)
    return ingest_document(
        content, source=source, tree_path=tree_path,
        llm_base_url=llm_base_url, llm_model=llm_model,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m core.doc_ingest <file_path>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"Ingesting: {path}")
    result = ingest_file(path)
    print(f"\nExtracted {result['count']} claims from {result['source']}:")
    for i, leaf in enumerate(result["leaves"], 1):
        print(f"  {i}. [{leaf['id'][:8]}] {leaf['content'][:80]}")
    print(f"\nTree root hash: {result['root_hash'][:24]}...")

#!/usr/bin/env python3
"""
generate_graph.py — Reads live tree + synapses, embeds data into synapse_graph.html.

Usage:
    python3 generate_graph.py
    open synapse_graph.html
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TREE_FILE = os.path.join(SCRIPT_DIR, "..", "data", "tree.json")
SYNAPSES_FILE = os.path.join(SCRIPT_DIR, "..", "data", "synapses.json")
TEMPLATE = os.path.join(SCRIPT_DIR, "synapse_graph_template.html")
OUTPUT = os.path.join(SCRIPT_DIR, "synapse_graph.html")  # written to demo/


def main():
    # Load tree
    if not os.path.exists(TREE_FILE):
        print(f"Error: tree file not found at {TREE_FILE}")
        sys.exit(1)
    with open(TREE_FILE) as f:
        tree = json.load(f)

    # Load synapses
    if not os.path.exists(SYNAPSES_FILE):
        print(f"Error: synapses file not found at {SYNAPSES_FILE}")
        sys.exit(1)
    with open(SYNAPSES_FILE) as f:
        synapses = json.load(f)

    # Collect leaf IDs referenced in synapses
    referenced_ids = set()
    for s in synapses.get("synapses", []):
        referenced_ids.add(s["from_leaf"])
        referenced_ids.add(s["to_leaf"])

    # Extract only referenced leaves, tagged with branch name
    nodes = []
    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            if leaf["id"] in referenced_ids:
                nodes.append({
                    "id": leaf["id"],
                    "content": leaf["content"],
                    "branch": branch_name,
                    "source": leaf.get("source", ""),
                    "confidence": leaf.get("confidence", 0.7),
                    "created": leaf.get("created", ""),
                })

    # Build edges
    edges = []
    for s in synapses.get("synapses", []):
        edges.append({
            "id": s["id"],
            "from": s["from_leaf"],
            "to": s["to_leaf"],
            "relation": s["relation"],
            "note": s.get("note", ""),
        })

    embedded = {
        "nodes": nodes,
        "edges": edges,
        "root_hash": synapses.get("root_hash", ""),
        "synapse_count": len(edges),
        "node_count": len(nodes),
    }

    # Read template and inject data
    if not os.path.exists(TEMPLATE):
        print(f"Error: template not found at {TEMPLATE}")
        sys.exit(1)
    with open(TEMPLATE) as f:
        template = f.read()

    data_json = json.dumps(embedded, indent=2)
    html = template.replace("/*__GRAPH_DATA__*/", f"const GRAPH_DATA = {data_json};")

    with open(OUTPUT, "w") as f:
        f.write(html)

    print(f"Generated {OUTPUT}")
    print(f"  Nodes: {len(nodes)}, Edges: {len(edges)}")
    print(f"  Root hash: {synapses.get('root_hash', 'N/A')[:16]}...")


if __name__ == "__main__":
    main()

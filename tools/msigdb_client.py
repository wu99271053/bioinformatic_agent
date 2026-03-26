"""
Fetch genes from MSigDB gene sets matching a biological term.

MSigDB has no public REST API, so this tool downloads GMT (Gene Matrix
Transposed) files from the Broad Institute CDN and searches gene set names
for keyword matches.

Supported collections:
    H   — Hallmark gene sets (default, 50 curated gene sets)
    C2  — Curated gene sets (pathway databases, publications)
    C5  — GO gene sets (genes annotated with same GO terms)
    C6  — Oncogenic signature gene sets
    C7  — Immunologic signature gene sets

GMT files are cached locally under data/.msigdb_cache/ to avoid re-downloading.

Usage:
    python -m tools.msigdb_client --biology_term glycolysis
    python -m tools.msigdb_client --biology_term "apoptosis" --collection C2
"""

import os
import re
import requests
import argparse
import json
from typing import List, Dict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MSIGDB_VERSION = "2024.1.Hs"
MSIGDB_BASE_URL = (
    f"https://data.broadinstitute.org/gsea-msigdb/msigdb/release/{MSIGDB_VERSION}"
)

# Map user-friendly collection codes to GMT file prefixes
COLLECTION_MAP = {
    "H":  "h.all",
    "C1": "c1.all",
    "C2": "c2.all",
    "C3": "c3.all",
    "C4": "c4.all",
    "C5": "c5.all",
    "C6": "c6.all",
    "C7": "c7.all",
    "C8": "c8.all",
}

CACHE_DIR = os.path.join(PROJECT_ROOT, "data", ".msigdb_cache")


def _gmt_url(collection: str) -> str:
    """Build the download URL for a collection's symbols GMT file."""
    prefix = COLLECTION_MAP.get(collection.upper())
    if prefix is None:
        raise ValueError(
            f"Unknown MSigDB collection '{collection}'. "
            f"Supported: {', '.join(sorted(COLLECTION_MAP.keys()))}"
        )
    filename = f"{prefix}.v{MSIGDB_VERSION}.symbols.gmt"
    return f"{MSIGDB_BASE_URL}/{filename}"


def _get_cached_gmt(collection: str) -> str:
    """Download the GMT file if not cached; return path to local copy."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    prefix = COLLECTION_MAP[collection.upper()]
    local_filename = f"{prefix}.v{MSIGDB_VERSION}.symbols.gmt"
    local_path = os.path.join(CACHE_DIR, local_filename)

    if os.path.exists(local_path):
        return local_path

    url = _gmt_url(collection)
    print(f"[MSigDB] Downloading {url} ...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    with open(local_path, "w", encoding="utf-8") as f:
        f.write(resp.text)

    print(f"[MSigDB] Cached → {local_path}")
    return local_path


def _parse_gmt(path: str) -> List[Dict]:
    """
    Parse a GMT file into a list of gene sets.

    GMT format: one line per gene set
        <set_name>\t<description_or_url>\t<gene1>\t<gene2>\t...
    """
    gene_sets = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            gene_sets.append({
                "name": parts[0],
                "description": parts[1],
                "genes": parts[2:],
            })
    return gene_sets


def _keyword_match(text: str, keywords: List[str]) -> bool:
    """Check if ALL keywords appear in the text (case-insensitive)."""
    text_lower = text.lower()
    return all(kw in text_lower for kw in keywords)


def fetch_genes_from_msigdb(
    biology_term: str, collection: str = "H"
) -> List[Dict[str, str]]:
    """
    Fetch genes from MSigDB gene sets matching a biology term.

    Downloads the GMT file for the requested collection from the Broad
    Institute CDN, searches gene set names for keyword matches, and
    returns the union of genes from all matching gene sets.

    Args:
        biology_term: Human-readable biological process (e.g. 'glycolysis').
                      Use the label returned by map_term_to_ontology.
        collection:   MSigDB collection code (default 'H' = Hallmark).
                      Options: H, C1, C2, C3, C4, C5, C6, C7, C8.

    Returns:
        List of dicts with keys: gene_id, gene_symbol, description, evidence_used.

    Raises:
        ValueError: If no matching gene sets or no genes are found.
    """
    collection = collection.upper()
    if collection not in COLLECTION_MAP:
        raise ValueError(
            f"Unknown MSigDB collection '{collection}'. "
            f"Supported: {', '.join(sorted(COLLECTION_MAP.keys()))}"
        )

    gmt_path = _get_cached_gmt(collection)
    gene_sets = _parse_gmt(gmt_path)

    # Split the biology term into keywords for multi-word matching
    keywords = [kw.lower() for kw in biology_term.strip().split() if kw]

    matching_sets = [
        gs for gs in gene_sets
        if _keyword_match(gs["name"], keywords)
        or _keyword_match(gs["description"], keywords)
    ]

    if not matching_sets:
        raise ValueError(
            f"MSigDB ({collection}): no gene sets matched term '{biology_term}'. "
            f"Try a different keyword or collection."
        )

    # Collect unique genes across all matching gene sets
    seen: set = set()
    results: List[Dict[str, str]] = []
    matched_set_names = [gs["name"] for gs in matching_sets]

    for gs in matching_sets:
        for gene_symbol in gs["genes"]:
            if gene_symbol in seen:
                continue
            seen.add(gene_symbol)
            results.append({
                "gene_id": gene_symbol,
                "gene_symbol": gene_symbol,
                "description": "",
                "evidence_used": f"MSigDB:{collection}:{gs['name']}",
            })

    if not results:
        raise ValueError(
            f"MSigDB ({collection}): matched gene sets {matched_set_names} "
            f"but they contained no genes."
        )

    return results


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch genes from MSigDB gene sets for a biological term."
    )
    parser.add_argument(
        "--biology_term", required=True,
        help="Biological process label (e.g. 'glycolysis')"
    )
    parser.add_argument(
        "--collection", default="H",
        help=(
            "MSigDB collection code (default: H = Hallmark). "
            "Options: H, C1, C2, C3, C4, C5, C6, C7, C8"
        ),
    )
    args = parser.parse_args()

    records = fetch_genes_from_msigdb(args.biology_term, args.collection)
    print(json.dumps(records, indent=2))
    print(f"\nTotal: {len(records)} genes")

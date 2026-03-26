"""
Query OpenTargets Platform for gene-disease associations.

Two functions:
  - query_opentargets: gene → diseases (find what diseases a gene is linked to)
  - query_disease_genes: disease → genes (find what genes are linked to a disease,
    then intersect with your gene list)

The disease-first approach is preferred for comparing a gene list against a disease,
as it requires only 1-2 API calls instead of N calls (one per gene).

Usage:
    python -m tools.opentargets_client --gene_symbol TP53
    python -m tools.opentargets_client --gene_symbols "TP53,HK2,PKM" --disease_filter cancer
    python -m tools.opentargets_client --disease "brain tumor" --compare_genes "ATG7,MTOR,TP53,BECN2"
"""

import os
import time
import requests
import argparse
import json
from typing import List, Dict, Any, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

API_URL = "https://api.platform.opentargets.org/api/v4/graphql"
TIMEOUT = 30
MAX_RETRIES = 2
RETRY_DELAY = 2

# --- GraphQL queries ---

SEARCH_GENE_QUERY = """
query SearchGene($symbol: String!) {
    search(queryString: $symbol, entityNames: ["target"], page: {size: 5, index: 0}) {
        hits { id, name, description }
    }
}
"""

SEARCH_DISEASE_QUERY = """
query SearchDisease($term: String!) {
    search(queryString: $term, entityNames: ["disease"], page: {size: 5, index: 0}) {
        hits { id, name, description }
    }
}
"""

GENE_ASSOCIATIONS_QUERY = """
query DiseaseAssociations($ensemblId: String!, $size: Int!) {
    target(ensemblId: $ensemblId) {
        approvedSymbol
        approvedName
        associatedDiseases(page: {size: $size, index: 0}) {
            count
            rows {
                disease {
                    id
                    name
                    therapeuticAreas { id, name }
                }
                score
            }
        }
    }
}
"""

DISEASE_GENES_QUERY = """
query GenesForDisease($efoId: String!, $size: Int!) {
    disease(efoId: $efoId) {
        id
        name
        associatedTargets(page: {size: $size, index: 0}) {
            count
            rows {
                target { approvedSymbol, id }
                score
            }
        }
    }
}
"""

MAX_GENES_PER_CALL = 10


def _api_post(payload: dict) -> dict:
    """POST to OpenTargets with retry logic."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(API_URL, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"   [RETRY] {type(e).__name__}, waiting {wait}s ...")
                time.sleep(wait)
            else:
                raise


def _resolve_symbol_to_ensembl(gene_symbol: str) -> str:
    """Resolve a gene symbol to an Ensembl ID via the OpenTargets search API."""
    data = _api_post({
        "query": SEARCH_GENE_QUERY,
        "variables": {"symbol": gene_symbol},
    })
    hits = data.get("data", {}).get("search", {}).get("hits", [])

    for hit in hits:
        if hit.get("name", "").upper() == gene_symbol.upper():
            return hit["id"]
    if hits:
        return hits[0]["id"]

    raise ValueError(
        f"OpenTargets: gene symbol '{gene_symbol}' not found."
    )


def _resolve_disease_term(disease_term: str) -> tuple[str, str]:
    """Resolve a disease term to an EFO/MONDO ID. Returns (id, name)."""
    data = _api_post({
        "query": SEARCH_DISEASE_QUERY,
        "variables": {"term": disease_term},
    })
    hits = data.get("data", {}).get("search", {}).get("hits", [])

    if not hits:
        raise ValueError(
            f"OpenTargets: disease term '{disease_term}' not found. "
            f"Try terms like 'glioblastoma', 'liver cancer', 'breast carcinoma'."
        )

    # Return the top hit
    best = hits[0]
    print(f"[OpenTargets] Disease '{disease_term}' → {best['id']} ({best['name']})")
    if len(hits) > 1:
        others = ", ".join(f"{h['name']} ({h['id']})" for h in hits[1:3])
        print(f"   Also found: {others}")

    return best["id"], best["name"]


# ═══════════════════════════════════════════════════════════════
# Function 1: gene → diseases  (keep for single gene lookups)
# ═══════════════════════════════════════════════════════════════

def query_opentargets(
    gene_symbols: List[str],
    disease_filter: str = "",
    max_diseases: int = 10,
) -> List[Dict[str, Any]]:
    """
    Find diseases associated with one or more genes via OpenTargets.

    Use this when you have a small number of genes (1-5) and want to know
    what diseases they are linked to. For comparing a gene list against
    a specific disease, use query_disease_genes instead (much faster).

    Args:
        gene_symbols:   List of HGNC gene symbols (max 10 per call).
        disease_filter: Optional keyword to filter disease names.
        max_diseases:   Max diseases per gene (default: 10).

    Returns:
        List of dicts with: gene_symbol, ensembl_id, disease_id,
        disease_name, therapeutic_areas, association_score.
    """
    if len(gene_symbols) > MAX_GENES_PER_CALL:
        print(f"[OpenTargets] Capping from {len(gene_symbols)} to {MAX_GENES_PER_CALL} genes")
        gene_symbols = gene_symbols[:MAX_GENES_PER_CALL]

    results = []
    failed_genes = []

    for symbol in gene_symbols:
        try:
            print(f"[OpenTargets] Resolving {symbol} ...")
            ensembl_id = _resolve_symbol_to_ensembl(symbol)
            print(f"[OpenTargets] {symbol} → {ensembl_id}")

            fetch_size = max_diseases * 3 if disease_filter else max_diseases
            data = _api_post({
                "query": GENE_ASSOCIATIONS_QUERY,
                "variables": {"ensemblId": ensembl_id, "size": fetch_size},
            })

            target = data.get("data", {}).get("target")
            if not target:
                continue

            approved = target.get("approvedSymbol", symbol)
            rows = target.get("associatedDiseases", {}).get("rows", [])
            total = target.get("associatedDiseases", {}).get("count", 0)
            print(f"[OpenTargets] {approved}: {total} total associations")

            matched = 0
            filter_lower = disease_filter.lower() if disease_filter else ""

            for row in rows:
                disease = row.get("disease", {})
                disease_name = disease.get("name", "")

                if filter_lower:
                    areas = [a.get("name", "") for a in disease.get("therapeuticAreas", [])]
                    searchable = f"{disease_name} {' '.join(areas)}".lower()
                    if filter_lower not in searchable:
                        continue

                results.append({
                    "gene_symbol": approved,
                    "ensembl_id": ensembl_id,
                    "disease_id": disease.get("id", ""),
                    "disease_name": disease_name,
                    "therapeutic_areas": [a.get("name", "") for a in disease.get("therapeuticAreas", [])],
                    "association_score": round(row.get("score", 0), 4),
                })
                matched += 1
                if matched >= max_diseases:
                    break

        except Exception as e:
            print(f"   [WARN] Failed for {symbol}: {e}")
            failed_genes.append(symbol)

    if failed_genes:
        print(f"[OpenTargets] Skipped {len(failed_genes)} genes: {failed_genes}")

    if not results:
        filter_msg = f" matching '{disease_filter}'" if disease_filter else ""
        raise ValueError(f"OpenTargets: no disease associations{filter_msg} found for: {gene_symbols}")

    return results


# ═══════════════════════════════════════════════════════════════
# Function 2: disease → genes → intersect  (PREFERRED for lists)
# ═══════════════════════════════════════════════════════════════

def query_disease_genes(
    disease_term: str,
    gene_list: Optional[List[str]] = None,
    max_genes: int = 500,
) -> Dict[str, Any]:
    """
    Find genes associated with a disease. Optionally intersect with your gene list.

    This is the PREFERRED method when you already have a gene list and want
    to check which genes are implicated in a specific disease. It makes only
    1-2 API calls regardless of gene list size (vs. N calls for query_opentargets).

    Args:
        disease_term: Disease or cancer name (e.g. 'brain tumor', 'hepatocellular
                      carcinoma', 'breast cancer'). Resolved via search.
        gene_list:    Optional list of HGNC gene symbols to intersect with.
                      If provided, only returns genes that are in BOTH the
                      disease's associated genes AND your list.
        max_genes:    Max disease-associated genes to fetch (default: 500).
                      Increase if you need deeper coverage.

    Returns:
        Dict with:
          - disease_id, disease_name: the resolved disease
          - total_associated_genes: how many genes OpenTargets links to this disease
          - top_genes: top 10 disease-associated genes (for context)
          - intersection: (if gene_list provided) list of {gene_symbol, score}
            for genes that appear in both your list and the disease's gene list
          - intersection_count: number of overlapping genes
          - genes_not_found: genes from your list NOT associated with this disease
    """
    # Step 1: Resolve disease term to EFO/MONDO ID
    disease_id, disease_name = _resolve_disease_term(disease_term)

    # Step 2: Fetch associated genes
    print(f"[OpenTargets] Fetching genes for {disease_name} ...")
    data = _api_post({
        "query": DISEASE_GENES_QUERY,
        "variables": {"efoId": disease_id, "size": max_genes},
    })

    disease_data = data.get("data", {}).get("disease")
    if not disease_data:
        raise ValueError(f"OpenTargets: no data for disease '{disease_id}'")

    assoc = disease_data.get("associatedTargets", {})
    total_count = assoc.get("count", 0)
    rows = assoc.get("rows", [])

    print(f"[OpenTargets] {disease_name}: {total_count} total associated genes, fetched top {len(rows)}")

    # Build gene → score lookup
    disease_genes = {}
    for row in rows:
        sym = row["target"]["approvedSymbol"]
        score = round(row["score"], 4)
        disease_genes[sym] = score

    # Top 10 for context
    top_genes = [
        {"gene_symbol": sym, "score": score}
        for sym, score in list(disease_genes.items())[:10]
    ]

    result = {
        "disease_id": disease_id,
        "disease_name": disease_name,
        "total_associated_genes": total_count,
        "top_genes": top_genes,
    }

    # Step 3: Intersect if gene list provided
    if gene_list:
        gene_set = set(g.upper() for g in gene_list)
        disease_gene_set = set(g.upper() for g in disease_genes.keys())

        intersection = []
        for sym in gene_list:
            if sym.upper() in disease_gene_set:
                # Find the original-case key
                score = disease_genes.get(sym, 0)
                if score == 0:
                    # Try case-insensitive
                    for k, v in disease_genes.items():
                        if k.upper() == sym.upper():
                            score = v
                            break
                intersection.append({
                    "gene_symbol": sym,
                    "association_score": score,
                })

        not_found = [g for g in gene_list if g.upper() not in disease_gene_set]

        # Sort intersection by score descending
        intersection.sort(key=lambda x: x["association_score"], reverse=True)

        result["intersection"] = intersection
        result["intersection_count"] = len(intersection)
        result["input_gene_count"] = len(gene_list)
        result["genes_not_found_count"] = len(not_found)
        # Only include a few not-found for context
        result["genes_not_found_sample"] = not_found[:5] if len(not_found) > 5 else not_found

        print(
            f"[OpenTargets] Intersection: {len(intersection)}/{len(gene_list)} "
            f"of your genes are associated with {disease_name}"
        )

    return result


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Query OpenTargets for gene-disease associations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # gene → diseases
    g2d = subparsers.add_parser("gene", help="Find diseases for a gene")
    g2d_group = g2d.add_mutually_exclusive_group(required=True)
    g2d_group.add_argument("--gene_symbol", help="Single gene symbol")
    g2d_group.add_argument("--gene_symbols", help="Comma-separated gene symbols")
    g2d.add_argument("--disease_filter", default="")
    g2d.add_argument("--max_diseases", type=int, default=10)

    # disease → genes (+ optional intersection)
    d2g = subparsers.add_parser("disease", help="Find genes for a disease")
    d2g.add_argument("--disease", required=True, help="Disease name (e.g. 'brain tumor')")
    d2g.add_argument("--compare_genes", help="Comma-separated gene symbols to intersect")
    d2g.add_argument("--max_genes", type=int, default=500)

    args = parser.parse_args()

    if args.command == "gene":
        symbols = (
            [args.gene_symbol]
            if args.gene_symbol
            else [s.strip() for s in args.gene_symbols.split(",")]
        )
        assocs = query_opentargets(symbols, args.disease_filter, args.max_diseases)
        print(json.dumps(assocs, indent=2))
        print(f"\nTotal: {len(assocs)} associations")

    elif args.command == "disease":
        gene_list = (
            [s.strip() for s in args.compare_genes.split(",")]
            if args.compare_genes else None
        )
        result = query_disease_genes(args.disease, gene_list, args.max_genes)
        print(json.dumps(result, indent=2))

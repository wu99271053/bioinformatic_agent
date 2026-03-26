"""
Fetch genes from KEGG pathways matching a biological term.

Three-step approach (KEGG has no direct GO-ID → gene endpoint):
  1. Search pathways by keyword:   rest.kegg.jp/find/pathway/{term}
  2. Get genes per pathway:        rest.kegg.jp/link/{organism}/{pathway_id}
  3. Convert KEGG IDs to UniProt:  rest.kegg.jp/conv/uniprot/{kegg_ids}

Note: KEGG conv only works in the direction KEGG-gene-ID → UniProt (not the reverse),
so the output of this tool uses UniProtKB IDs, consistent with QuickGO and Reactome.

Usage:
    python -m tools.kegg_client --biology_term glycolysis
    python -m tools.kegg_client --biology_term "one carbon metabolism" --organism hsa
"""

import requests
import argparse
import json
import time
from typing import List, Dict

CONV_BATCH = 50       # stay within KEGG URL length limits
KEGG_RATE_DELAY = 0.35  # KEGG enforces ~3 req/sec; 0.35 s gives a small safety margin


def _find_pathway_ids(biology_term: str, organism: str) -> List[str]:
    """Search KEGG for pathways matching the term, return organism-specific IDs."""
    url = f"https://rest.kegg.jp/find/pathway/{requests.utils.quote(biology_term)}"
    time.sleep(KEGG_RATE_DELAY)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    pathway_ids = []
    for line in resp.text.strip().splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        # format: "path:map00010"
        raw_id = parts[0].strip().replace("path:", "")        # "map00010"
        # Convert reference map ID to organism-specific: map00010 → hsa00010
        org_id = raw_id.replace("map", organism)              # "hsa00010"
        if org_id not in pathway_ids:
            pathway_ids.append(org_id)
        if len(pathway_ids) >= 3:
            break

    return pathway_ids


def _get_kegg_gene_ids(pathway_id: str, organism: str) -> List[str]:
    """Return KEGG gene IDs (e.g. 'hsa:10458') for a given pathway."""
    url = f"https://rest.kegg.jp/link/{organism}/{pathway_id}"
    time.sleep(KEGG_RATE_DELAY)
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200 or not resp.text.strip():
        return []

    gene_ids = []
    for line in resp.text.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            gene_ids.append(parts[1].strip())   # e.g. "hsa:10458"
    return gene_ids


def _convert_to_uniprot(kegg_gene_ids: List[str]) -> Dict[str, str]:
    """Batch-convert KEGG gene IDs to UniProt accessions. Returns {kegg_id: uniprot_ac}."""
    mapping: Dict[str, str] = {}
    for i in range(0, len(kegg_gene_ids), CONV_BATCH):
        batch = kegg_gene_ids[i:i + CONV_BATCH]
        entries = "+".join(batch)
        url = f"https://rest.kegg.jp/conv/uniprot/{entries}"
        time.sleep(KEGG_RATE_DELAY)
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200 or not resp.text.strip():
            continue
        for line in resp.text.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                kegg_id = parts[0].strip()       # "hsa:10458"
                up_entry = parts[1].strip()      # "up:Q9UQB8"
                uniprot_ac = up_entry.replace("up:", "")
                mapping[kegg_id] = uniprot_ac
    return mapping


def fetch_genes_from_kegg(biology_term: str, organism: str = "hsa") -> List[Dict[str, str]]:
    """
    Fetch genes from KEGG pathways matching a biology term.

    Args:
        biology_term: Human-readable biological process (e.g. 'glycolysis').
                      Use the label returned by map_term_to_ontology.
        organism:     KEGG organism code (default 'hsa' = Homo sapiens).

    Returns:
        List of dicts with keys: gene_id (UniProtKB), gene_symbol, description, evidence_used.

    Raises:
        ValueError: If no pathways or no genes are found for the term.
    """
    pathway_ids = _find_pathway_ids(biology_term, organism)
    if not pathway_ids:
        raise ValueError(f"KEGG: no pathways found for term '{biology_term}'.")

    # Collect unique KEGG gene IDs across all matching pathways
    kegg_gene_ids: List[str] = []
    seen_kegg: set = set()
    for pid in pathway_ids:
        for gid in _get_kegg_gene_ids(pid, organism):
            if gid not in seen_kegg:
                seen_kegg.add(gid)
                kegg_gene_ids.append(gid)

    if not kegg_gene_ids:
        raise ValueError(f"KEGG: pathways found for '{biology_term}' but contained no genes.")

    # Convert KEGG IDs → UniProt accessions
    uniprot_map = _convert_to_uniprot(kegg_gene_ids)

    if not uniprot_map:
        raise ValueError(
            f"KEGG: genes found for '{biology_term}' but UniProt conversion returned nothing."
        )

    results: List[Dict[str, str]] = []
    seen_up: set = set()
    for kegg_id in kegg_gene_ids:
        uniprot_ac = uniprot_map.get(kegg_id)
        if not uniprot_ac or uniprot_ac in seen_up:
            continue
        seen_up.add(uniprot_ac)
        results.append({
            "gene_id": f"UniProtKB:{uniprot_ac}",
            "gene_symbol": "",
            "description": "",
            "evidence_used": "KEGG:pathway",
        })

    return results


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch genes from KEGG pathways for a biological term."
    )
    parser.add_argument(
        "--biology_term", required=True,
        help="Biological process label (e.g. 'glycolysis')"
    )
    parser.add_argument(
        "--organism", default="hsa",
        help="KEGG organism code (default: hsa)"
    )
    args = parser.parse_args()

    records = fetch_genes_from_kegg(args.biology_term, args.organism)
    print(json.dumps(records, indent=2))
    print(f"\nTotal: {len(records)} genes")

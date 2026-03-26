"""
Fetch genes from Reactome pathways matching a biological term.

Reactome has no direct GO-ID → pathway endpoint, so this tool uses a
two-step approach: search for relevant pathways by term label, then
collect UniProt participants from the top matching pathways.

Usage:
    python -m tools.reactome_client --biology_term glycolysis
    python -m tools.reactome_client --biology_term "one carbon metabolism" --top_n 5
"""

import requests
import argparse
import json
from typing import List, Dict

SEARCH_URL = "https://reactome.org/ContentService/search/query"
PARTICIPANTS_URL = "https://reactome.org/ContentService/data/participants/{stId}"


def fetch_genes_from_reactome(biology_term: str, taxon_id: str = "9606") -> List[Dict[str, str]]:
    """
    Fetch UniProt-identified genes from Reactome pathways matching a biology term.

    Uses the biology term label (e.g. 'glycolysis') rather than a GO ID because
    Reactome's REST API has no direct GO-ID → pathway endpoint.

    Args:
        biology_term: Human-readable biological process name (e.g. 'glycolysis').
        taxon_id:     NCBI taxon ID — currently used to filter to Homo sapiens (9606).
                      Non-human organisms are not yet supported by this implementation.

    Returns:
        List of dicts with keys: gene_id, gene_symbol, description, evidence_used.

    Raises:
        ValueError: If no Reactome pathways or participants are found for the term.
    """
    # Step 1: search for human pathways matching the term
    search_params = {
        "query": biology_term,
        "types": "Pathway",
        "species": "Homo sapiens",
        "cluster": "true",
    }
    search_resp = requests.get(SEARCH_URL, params=search_params, timeout=20)
    search_resp.raise_for_status()

    search_data = search_resp.json()

    # Extract stable IDs from the top results
    pathway_ids: List[str] = []
    for group in search_data.get("results", []):
        for entry in group.get("entries", []):
            st_id = entry.get("stId", "")
            if st_id and st_id not in pathway_ids:
                pathway_ids.append(st_id)
            if len(pathway_ids) >= 3:
                break
        if len(pathway_ids) >= 3:
            break

    if not pathway_ids:
        raise ValueError(f"Reactome: no pathways found for term '{biology_term}'.")

    # Step 2: collect participants from each pathway, deduplicate by gene_id
    seen: set = set()
    results: List[Dict[str, str]] = []

    for st_id in pathway_ids:
        part_url = PARTICIPANTS_URL.format(stId=st_id)
        part_resp = requests.get(part_url, timeout=20)
        if part_resp.status_code != 200:
            continue

        participants = part_resp.json()
        for participant in participants:
            display_name = participant.get("displayName", "")
            for ref in participant.get("refEntities", []):
                url = ref.get("url", "")
                identifier = ref.get("identifier", "")
                # Only keep UniProt-referenced entries
                if "uniprot" not in url.lower() or not identifier:
                    continue
                gene_id = f"UniProtKB:{identifier}"
                if gene_id in seen:
                    continue
                seen.add(gene_id)
                results.append({
                    "gene_id": gene_id,
                    "gene_symbol": "",
                    "description": display_name,
                    "evidence_used": "Reactome:pathway",
                })

    if not results:
        raise ValueError(
            f"Reactome: found pathways for '{biology_term}' but no UniProt participants."
        )

    return results


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch genes from Reactome pathways for a biological term."
    )
    parser.add_argument(
        "--biology_term", required=True,
        help="Biological process label (e.g. 'glycolysis')"
    )
    parser.add_argument(
        "--taxon_id", default="9606",
        help="NCBI taxon ID (default: 9606 = Homo sapiens)"
    )
    args = parser.parse_args()

    records = fetch_genes_from_reactome(args.biology_term, args.taxon_id)
    print(json.dumps(records, indent=2))
    print(f"\nTotal: {len(records)} genes")

"""
Translate gene IDs between namespaces using MyGene.info.

MyGene.info is a free, comprehensive gene annotation service that supports
ID mapping across many formats including non-protein-coding genes (unlike UniProt,
which only covers protein-coding genes).

Supported to_format values (MyGene.info field names):
    entrezgene   → NCBI Entrez Gene ID    (default, most common)
    symbol       → official gene symbol
    ensembl      → Ensembl gene ID

Input IDs: accepts UniProtKB accessions with or without the 'UniProtKB:' prefix.
    "UniProtKB:P04818" → queries MyGene.info by UniProt accession P04818
    "P04818"           → same result

Usage:
    python -m tools.id_translator --ids "UniProtKB:P04818,UniProtKB:P11586"
    python -m tools.id_translator --ids "UniProtKB:P04818" --to_format symbol
"""

import requests
import argparse
import json
from typing import List, Dict

MYGENE_URL = "https://mygene.info/v3/query"
BATCH_SIZE = 1000   # MyGene.info supports large batches


def _strip_uniprot_prefix(gene_id: str) -> str:
    """Strip 'UniProtKB:' or 'uniprot:' prefix to get the bare accession."""
    for prefix in ("UniProtKB:", "uniprot:"):
        if gene_id.startswith(prefix):
            return gene_id[len(prefix):]
    return gene_id


def translate_gene_ids(gene_ids: List[str], to_format: str = "entrezgene") -> List[Dict[str, str]]:
    """
    Translate UniProtKB gene IDs to another namespace via MyGene.info.

    Args:
        gene_ids:  List of gene IDs (e.g. ['UniProtKB:P04818', 'UniProtKB:P11586']).
                   'UniProtKB:' prefix is stripped automatically.
        to_format: Target field in MyGene.info (default: 'entrezgene').
                   Other options: 'symbol', 'ensembl'.

    Returns:
        List of dicts: [{"from_id": "UniProtKB:P04818", "to_id": "7298",
                          "to_format": "entrezgene"}, ...]
        IDs with no mapping in MyGene.info are silently omitted.

    Raises:
        ValueError: If MyGene.info returns no mappings for any of the provided IDs.
    """
    # Map 'ensembl' shorthand to the actual MyGene.info dotted field
    mygene_field = "ensembl.gene" if to_format == "ensembl" else to_format

    results: List[Dict[str, str]] = []

    # Build lookup: bare accession → original input ID
    bare_to_original: Dict[str, str] = {
        _strip_uniprot_prefix(gid): gid for gid in gene_ids
    }
    bare_ids = list(bare_to_original.keys())

    for i in range(0, len(bare_ids), BATCH_SIZE):
        batch = bare_ids[i:i + BATCH_SIZE]

        resp = requests.post(
            MYGENE_URL,
            data={
                "q": ",".join(batch),
                "scopes": "uniprot",
                "fields": mygene_field,
                "species": "human",
            },
            timeout=30,
        )
        resp.raise_for_status()

        for hit in resp.json():
            if hit.get("notfound"):
                continue

            query_bare = hit.get("query", "")
            original_id = bare_to_original.get(query_bare, query_bare)

            raw_value = hit.get(mygene_field)
            if raw_value is None:
                # try top-level key for dotted fields like "ensembl.gene"
                top_key = mygene_field.split(".")[0]
                nested = hit.get(top_key)
                if isinstance(nested, dict):
                    raw_value = nested.get("gene")
                elif isinstance(nested, list) and nested:
                    raw_value = nested[0].get("gene") if isinstance(nested[0], dict) else nested[0]

            if raw_value is None:
                continue

            # raw_value can be a list (e.g. multiple Entrez IDs); take the first
            if isinstance(raw_value, list):
                raw_value = raw_value[0]

            results.append({
                "from_id": original_id,
                "to_id": str(raw_value),
                "to_format": to_format,
            })

    if not results:
        raise ValueError(
            f"MyGene.info returned no mappings for the provided IDs "
            f"(to_format='{to_format}'). Ensure IDs are valid UniProt accessions."
        )

    return results


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Translate UniProtKB gene IDs to another namespace via MyGene.info."
    )
    parser.add_argument(
        "--ids", required=True,
        help="Comma-separated gene IDs (e.g. 'UniProtKB:P04818,UniProtKB:P11586')"
    )
    parser.add_argument(
        "--to_format", default="entrezgene",
        help="Target field: entrezgene (default), symbol, ensembl"
    )
    args = parser.parse_args()

    id_list = [x.strip() for x in args.ids.split(",") if x.strip()]
    mappings = translate_gene_ids(id_list, args.to_format)
    print(json.dumps(mappings, indent=2))
    print(f"\nTotal: {len(mappings)} mappings")

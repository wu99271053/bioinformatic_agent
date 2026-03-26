import requests
from typing import List, Dict
import argparse
import json

def fetch_genes_by_go_term(go_id: str, taxon_id: str = "9606") -> List[Dict[str, str]]:
    """
    Fetch authenticated genes associated with a specific GO ID from QuickGO.
    Uses server-side filtering to strictly request manual evidence codes.
    Includes a fail-fast safety net to block 'IEA' leakages.
    """
    url = "https://www.ebi.ac.uk/QuickGO/services/annotation/search"
    
    params = {
        "goId": go_id,
        "goUsage": "descendants", 
        "taxonId": taxon_id,      
        # --- THE FIX: Using ECO terms instead of 3-letter acronyms ---
        "evidenceCode": "ECO:0000352",      # "evidence used in manual assertion"
        "evidenceCodeUsage": "descendants", # Gets all subtypes (EXP, IDA, etc.)
        "limit": 100,             
        "page": 1                 
    }
    
    all_results = []
    max_pages = 2  # Cap results to prevent exceeding LLM token limits during tool passing
    
    while params["page"] <= max_pages:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status() 
        
        data = response.json()
        results = data.get("results", [])
        
        if not results:
            break
            
        all_results.extend(results)
        
        page_info = data.get("pageInfo", {})
        if page_info.get("current", 1) >= page_info.get("total", 1):
            break
            
        params["page"] += 1
        
    if not all_results:
        raise ValueError(f"No manual evidence genes found for GO ID '{go_id}'.")
        
    for ann in all_results:
        if ann.get("goEvidence") == "IEA":
            raise ValueError("FATAL: API returned IEA evidence despite strict filtering. Aborting to maintain data integrity.")
            
    unique_genes = {}
    for ann in all_results:
        symbol = ann.get("symbol")
        if symbol and symbol not in unique_genes:
            unique_genes[symbol] = {
                "gene_id": ann.get("geneProductId"),
                "gene_symbol": symbol,
                "description": ann.get("name", "N/A"),
                "evidence_used": ann.get("goEvidence")
            }
            
    return list(unique_genes.values())

# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch authenticated genes for a GO ID from QuickGO.")
    parser.add_argument("--go_id", type=str, required=True, help="The Gene Ontology ID (e.g., 'GO:0006730').")
    args = parser.parse_args()
    
    genes = fetch_genes_by_go_term(args.go_id)
    print(json.dumps(genes, indent=2))
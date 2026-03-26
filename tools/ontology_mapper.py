import requests
from typing import Optional, Dict, List
import argparse
import json

def map_term_to_ontology(biology_term: str, ontology: str = "go") -> List[Dict[str, str]]:
    """
    Queries the EMBL-EBI Ontology Lookup Service (OLS) to find the best 
    matching ontology IDs for a given biological term.
    
    Args:
        biology_term (str): The clean biological term (e.g., "one carbon metabolism").
        ontology (str): The specific ontology to search (default is "go" for Gene Ontology).
        
    Returns:
        list: A list of dictionaries containing the 'id' and 'label' of top matches.
        
    Raises:
        ValueError: If no match is found.
        requests.exceptions.RequestException: If the API request fails.
    """
    url = "https://www.ebi.ac.uk/ols4/api/search"
    
    params = {
        "q": biology_term,
        "ontology": ontology,
        "rows": 5 
    }
    
    # 10-second timeout is best practice for agent tools
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status() 
    
    data = response.json()
    
    # Check if we actually got a match back
    if data["response"]["numFound"] == 0:
        raise ValueError(f"No match found for '{biology_term}' in {ontology.upper()}.")
        
    hits = []
    for doc in data["response"]["docs"]:
        if "obo_id" in doc and "label" in doc:
            hits.append({
                "id": doc.get("obo_id"),
                "label": doc.get("label")
            })
            
    return hits

# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Map a biological term to an ontology ID.")
    parser.add_argument("--term", type=str, required=True, help="The biological term to search (e.g., 'one carbon metabolism').")
    parser.add_argument("--ontology", type=str, default="go", help="The ontology to search (default: 'go').")
    args = parser.parse_args()
    
    try:
        results = map_term_to_ontology(args.term, args.ontology)
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"Failed to map term: {e}")
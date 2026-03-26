"""
Explore GDC (Genomic Data Commons) projects and available data types.

Two functions:
  - explore_gdc_projects: search for projects by keyword (disease, cancer type,
    organ). Returns matching projects with data category summaries.
  - explore_gdc_data_types: list all available data types with file counts
    for a specific project.

Usage:
    python -m tools.gdc_explore --search "liver cancer"
    python -m tools.gdc_explore --search "breast"
    python -m tools.gdc_explore --project_id TCGA-LIHC
"""

import os
import requests
import argparse
import json
from typing import List, Dict, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROJECTS_ENDPOINT = "https://api.gdc.cancer.gov/projects"
FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"

PROJECT_FIELDS = ",".join([
    "project_id",
    "name",
    "disease_type",
    "primary_site",
    "summary.case_count",
    "summary.file_count",
    "summary.data_categories.data_category",
    "summary.data_categories.file_count",
])


def explore_gdc_projects(keyword: str) -> List[Dict[str, Any]]:
    """
    Search GDC for projects matching a keyword.

    Searches across project_id, name, disease_type, and primary_site fields.
    Returns a summary of matching projects including available data categories.

    Args:
        keyword: Search term (e.g. 'liver cancer', 'breast', 'melanoma',
                 'TCGA-LIHC'). Case-insensitive keyword matching.

    Returns:
        List of dicts with keys: project_id, name, disease_type, primary_site,
        case_count, file_count, data_categories (list of {category, file_count}).

    Raises:
        ValueError: If no projects match the keyword.
    """
    # Fetch all projects — GDC only has ~91, so a full scan is fine
    resp = requests.get(
        PROJECTS_ENDPOINT,
        params={"fields": PROJECT_FIELDS, "size": 200, "format": "JSON"},
        timeout=20,
    )
    resp.raise_for_status()
    all_projects = resp.json().get("data", {}).get("hits", [])

    # Keyword match across multiple fields
    kw_lower = keyword.lower()
    keywords = kw_lower.split()

    results = []
    for proj in all_projects:
        # Build a searchable text blob from all relevant fields
        searchable = " ".join([
            proj.get("project_id", ""),
            proj.get("name", ""),
            " ".join(proj.get("disease_type", [])),
            " ".join(proj.get("primary_site", [])),
        ]).lower()

        if all(kw in searchable for kw in keywords):
            summary = proj.get("summary", {})
            data_cats = summary.get("data_categories", [])

            results.append({
                "project_id": proj.get("project_id", ""),
                "name": proj.get("name", ""),
                "disease_type": proj.get("disease_type", []),
                "primary_site": proj.get("primary_site", []),
                "case_count": summary.get("case_count", 0),
                "file_count": summary.get("file_count", 0),
                "data_categories": [
                    {
                        "category": cat.get("data_category", ""),
                        "file_count": cat.get("file_count", 0),
                    }
                    for cat in data_cats
                ],
            })

    if not results:
        raise ValueError(
            f"GDC: no projects matched keyword '{keyword}'. "
            f"Try broader terms like 'liver', 'lung', 'breast', 'melanoma'."
        )

    # Sort by case count descending (largest studies first)
    results.sort(key=lambda x: x["case_count"], reverse=True)
    return results


def explore_gdc_data_types(project_id: str) -> Dict[str, Any]:
    """
    List all available data types and file counts for a GDC project.

    Queries the GDC files endpoint to get a detailed breakdown of
    data_type values (e.g. 'Gene Expression Quantification',
    'miRNA Expression Quantification', 'Copy Number Segment').

    Args:
        project_id: GDC project ID (e.g. 'TCGA-LIHC', 'TCGA-BRCA').

    Returns:
        Dict with keys: project_id, total_files, data_types (list of
        {data_type, data_category, file_count}).

    Raises:
        ValueError: If the project is not found or has no files.
    """
    # Use facets to get aggregated counts by data_type
    filters = {
        "op": "in",
        "content": {
            "field": "cases.project.project_id",
            "value": [project_id],
        },
    }

    resp = requests.post(
        FILES_ENDPOINT,
        json={
            "filters": filters,
            "facets": "data_type,data_category",
            "size": 0,
            "format": "JSON",
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})

    total_files = data.get("pagination", {}).get("total", 0)
    if total_files == 0:
        raise ValueError(
            f"GDC: project '{project_id}' not found or has no files."
        )

    # Parse facet aggregations
    aggregations = data.get("aggregations", {})

    data_type_buckets = aggregations.get("data_type", {}).get("buckets", [])
    data_category_buckets = aggregations.get("data_category", {}).get("buckets", [])

    data_types = [
        {"data_type": b["key"], "file_count": b["doc_count"]}
        for b in data_type_buckets
    ]
    # Sort by file count descending
    data_types.sort(key=lambda x: x["file_count"], reverse=True)

    data_categories = [
        {"data_category": b["key"], "file_count": b["doc_count"]}
        for b in data_category_buckets
    ]
    data_categories.sort(key=lambda x: x["file_count"], reverse=True)

    return {
        "project_id": project_id,
        "total_files": total_files,
        "data_types": data_types,
        "data_categories": data_categories,
    }


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Explore GDC projects and data types."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--search",
        help="Search for projects by keyword (e.g. 'liver cancer', 'breast')",
    )
    group.add_argument(
        "--project_id",
        help="List data types for a specific project (e.g. 'TCGA-LIHC')",
    )
    args = parser.parse_args()

    if args.search:
        projects = explore_gdc_projects(args.search)
        for p in projects:
            cats = ", ".join(
                f"{c['category']}({c['file_count']})"
                for c in p["data_categories"]
            )
            print(
                f"{p['project_id']:20s} | {p['case_count']:>5d} cases | "
                f"{', '.join(p['primary_site'][:2])}"
            )
            print(f"{'':20s}   {p['name']}")
            print(f"{'':20s}   Data: {cats}")
            print()
        print(f"Total: {len(projects)} projects")
    else:
        info = explore_gdc_data_types(args.project_id)
        print(f"Project: {info['project_id']} ({info['total_files']} total files)\n")
        print("Data Types:")
        for dt in info["data_types"]:
            print(f"  {dt['data_type']:45s} {dt['file_count']:>6d} files")
        print("\nData Categories:")
        for dc in info["data_categories"]:
            print(f"  {dc['data_category']:45s} {dc['file_count']:>6d} files")

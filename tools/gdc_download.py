"""
Download RNA-Seq / miRNA data from the GDC (Genomic Data Commons) Portal.

Uses the GDC REST API for metadata, manifest, and file downloads — no external
gdc-client binary needed.

Two modes:
  - Full download: fetches metadata, generates manifest, downloads + extracts files.
  - Metadata-only (--metadata_only): fetches metadata and annotation only.

Usage:
    python -m tools.gdc_download --project_id TCGA-LIHC
    python -m tools.gdc_download --project_id TCGA-BRCA --metadata_only
    python -m tools.gdc_download --project_id TCGA-LIHC --data_type "miRNA Expression Quantification"
"""

import os
import json
import subprocess
import argparse
import requests
from typing import Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"
MANIFEST_ENDPOINT = "https://api.gdc.cancer.gov/manifest"


def download_gdc_data(
    project_id: str,
    data_type: str = "Gene Expression Quantification",
    experimental_strategy: str = "RNA-Seq",
    access: str = "open",
    extra_fields: List[str] = None,
    metadata_only: bool = False,
) -> Dict[str, Any]:
    """
    Fetch metadata, generate a manifest, and (optionally) download RNA-Seq/miRNA
    files for a specified GDC project via the GDC REST API.

    Args:
        project_id:             GDC project ID (e.g. 'TCGA-LIHC').
        data_type:              GDC data type filter. Common values:
                                  - 'Gene Expression Quantification' (default)
                                  - 'miRNA Expression Quantification'
                                  - 'Protein Expression Quantification'
                                  - 'Copy Number Segment'
        experimental_strategy:  GDC experimental strategy filter (default: 'RNA-Seq').
                                Common values: 'RNA-Seq', 'miRNA-Seq', 'WXS', 'WGS',
                                'Reverse Phase Protein Array', 'Methylation Array'.
        access:                 Access level filter (default: 'open').
                                Use 'open' for publicly available data.
        extra_fields:           Optional list of additional GDC metadata fields
                                to include (e.g. ['cases.diagnoses.tumor_stage',
                                'cases.diagnoses.primary_diagnosis']).
        metadata_only:          If True, fetch metadata and annotation only.

    Returns:
        Dict with keys: project_id, file_count, metadata_path, annotation_path,
        manifest_path (None if metadata_only), raw_dir.

    Raises:
        ValueError: If no files are found for the given filters.
    """
    # ----- Setup directories -----
    raw_dir = os.path.join(PROJECT_ROOT, "data", project_id, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    metadata_path = os.path.join(raw_dir, f"{project_id}_Metadata.json")
    annotation_path = os.path.join(raw_dir, f"{project_id}_Annotation.txt")

    # ----- Step 1: Fetch metadata -----
    filter_content = [
        {"op": "in", "content": {"field": "cases.project.project_id", "value": [project_id]}},
        {"op": "in", "content": {"field": "files.data_type", "value": [data_type]}},
        {"op": "in", "content": {"field": "files.access", "value": [access]}},
    ]
    if experimental_strategy:
        filter_content.append(
            {"op": "in", "content": {"field": "files.experimental_strategy", "value": [experimental_strategy]}}
        )

    filters = {"op": "and", "content": filter_content}

    fields = [
        "file_id",
        "file_name",
        "cases.submitter_id",
        "cases.case_id",
        "cases.samples.sample_type",
        "cases.samples.tumor_descriptor",
        "cases.samples.tissue_type",
        "cases.demographic.vital_status",
        "cases.demographic.days_to_death",
        "cases.diagnoses.year_of_diagnosis",
        "cases.demographic.year_of_death",
    ]
    if extra_fields:
        fields.extend(extra_fields)

    payload = {
        "filters": filters,
        "fields": ",".join(fields),
        "format": "JSON",
        "size": "2000",
    }

    print(f"[GDC] Fetching metadata for {project_id}")
    print(f"      data_type={data_type}, strategy={experimental_strategy}, access={access}")
    meta_resp = requests.post(FILES_ENDPOINT, json=payload, timeout=30)
    meta_resp.raise_for_status()
    meta_data = meta_resp.json()

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=2)

    hits = meta_data.get("data", {}).get("hits", [])
    file_ids = [hit["file_id"] for hit in hits]
    print(f"[GDC] Found {len(file_ids)} files for {project_id}")

    if not file_ids:
        raise ValueError(
            f"GDC: no files found for project '{project_id}' with "
            f"data_type='{data_type}', strategy='{experimental_strategy}', access='{access}'."
        )

    # ----- Step 1b: Generate annotation -----
    with open(annotation_path, "w", encoding="utf-8") as f:
        f.write("file_id\ttissue_type\n")
        for hit in hits:
            fid = hit["file_id"]
            tissue = (
                hit.get("cases", [{}])[0]
                .get("samples", [{}])[0]
                .get("tissue_type", "Unknown")
            )
            f.write(f"{fid}\t{tissue}\n")
    print(f"[GDC] Annotation saved → {annotation_path}")

    result = {
        "project_id": project_id,
        "file_count": len(file_ids),
        "metadata_path": metadata_path,
        "annotation_path": annotation_path,
        "manifest_path": None,
        "raw_dir": raw_dir,
    }

    if metadata_only:
        return result

    # ----- Step 2: Generate manifest -----
    print("[GDC] Generating manifest ...")
    manifest_path = os.path.join(raw_dir, f"{project_id}_Manifest.txt")
    manifest_resp = requests.post(MANIFEST_ENDPOINT, json={"ids": file_ids}, timeout=30)
    manifest_resp.raise_for_status()

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest_resp.text)
    print(f"[GDC] Manifest saved → {manifest_path}")
    result["manifest_path"] = manifest_path

    # ----- Step 3: Download via gdc-client -----
    gdc_client = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdc-client")

    if not os.path.exists(gdc_client):
        raise RuntimeError(
            f"gdc-client binary not found at {gdc_client}. "
            f"Download from https://gdc.cancer.gov/access-data/gdc-data-transfer-tool "
            f"and place it in the tools/ folder."
        )

    print(f"[GDC] Downloading {len(file_ids)} files via gdc-client ...")
    command = [gdc_client, "download", "-m", manifest_path, "-d", raw_dir]

    try:
        subprocess.run(command, check=True, text=True)
        print(f"[GDC] Download complete → {raw_dir}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gdc-client download failed (exit code {e.returncode}).")

    return result


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download RNA-Seq data from the GDC Portal."
    )
    parser.add_argument(
        "--project_id", required=True,
        help="The GDC Project ID (e.g., TCGA-LIHC, TCGA-BRCA)",
    )
    parser.add_argument(
        "--data_type", default="Gene Expression Quantification",
        help="GDC data type filter (default: 'Gene Expression Quantification')",
    )
    parser.add_argument(
        "--experimental_strategy", default="RNA-Seq",
        help="Experimental strategy (default: 'RNA-Seq'). Use 'miRNA-Seq' for miRNA.",
    )
    parser.add_argument(
        "--access", default="open",
        help="Access level filter (default: 'open')",
    )
    parser.add_argument(
        "--extra_fields",
        help="Comma-separated additional metadata fields (e.g. 'cases.diagnoses.tumor_stage')",
    )
    parser.add_argument(
        "--metadata_only", action="store_true",
        help="Fetch metadata and annotation only — skip data download",
    )
    args = parser.parse_args()

    ef = [f.strip() for f in args.extra_fields.split(",")] if args.extra_fields else None

    info = download_gdc_data(
        args.project_id,
        data_type=args.data_type,
        experimental_strategy=args.experimental_strategy,
        access=args.access,
        extra_fields=ef,
        metadata_only=args.metadata_only,
    )
    print(json.dumps(info, indent=2))


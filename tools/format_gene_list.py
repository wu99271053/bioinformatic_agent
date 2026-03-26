"""
Post-processing script: converts a raw JSON gene dump to a clean CSV.

Usage:
    python -m tools.format_gene_list --input data/glycolysis/raw/raw_genes_dump_1234.json
    python -m tools.format_gene_list --input data/glycolysis/raw/raw_genes_dump_1234.json --output my_genes.csv

The output CSV is written to the processed/ folder that sits alongside the raw/ folder.
The data/<term>/index.json entry for the source raw file is updated to record the link.

Input JSON may be either:
  - A plain list:              [{gene_id, gene_symbol, description, evidence_used}, ...]
  - A wrapped dict:            {"result": [...]}
"""

import os
import csv
import json
import argparse


def load_raw(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if not isinstance(data, list):
        raise ValueError(f"Unexpected JSON structure in {path}: expected a list or {{result: [...]}}")
    return data


def to_csv(records: list[dict], out_path: str) -> None:
    if not records:
        raise ValueError("No gene records to write.")
    fieldnames = ["gene_id", "gene_symbol", "description", "evidence_used"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def update_index(term_dir: str, raw_filename: str, processed_filename: str) -> None:
    index_path = os.path.join(term_dir, "index.json")
    if not os.path.exists(index_path):
        return
    with open(index_path, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    raw_key = f"raw/{raw_filename}"
    for entry in index_data.get("files", []):
        if entry.get("raw_file") == raw_key:
            pf = entry.setdefault("processed_files", [])
            link = f"processed/{processed_filename}"
            if link not in pf:
                pf.append(link)
            break

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)


def format_gene_list(input_path: str, output_filename: str | None = None) -> str:
    """
    Convert a raw gene JSON dump to CSV.

    Args:
        input_path:      Absolute or relative path to the raw JSON file.
        output_filename: Optional CSV filename. Defaults to the raw file's base name
                         with a .csv extension.

    Returns:
        Absolute path to the written CSV file.
    """
    input_path = os.path.abspath(input_path)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Derive sibling processed/ directory from the raw/ path
    raw_dir = os.path.dirname(input_path)
    term_dir = os.path.dirname(raw_dir)
    processed_dir = os.path.join(term_dir, "processed")
    os.makedirs(processed_dir, exist_ok=True)

    raw_basename = os.path.basename(input_path)
    if output_filename is None:
        output_filename = os.path.splitext(raw_basename)[0] + ".csv"
    safe_filename = os.path.basename(output_filename)
    out_path = os.path.join(processed_dir, safe_filename)

    records = load_raw(input_path)
    to_csv(records, out_path)
    update_index(term_dir, raw_basename, safe_filename)

    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert a raw gene JSON dump to a processed CSV."
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to the raw JSON file (e.g. data/glycolysis/raw/raw_genes_dump_123.json)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output CSV filename (default: same base name as input with .csv extension)"
    )
    args = parser.parse_args()

    out = format_gene_list(args.input, args.output)
    print(f"Saved CSV → {out}")

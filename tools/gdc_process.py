"""
Combine downloaded GDC TSV files into a single expression matrix.

Supports both mRNA (Gene Expression Quantification) and miRNA
(miRNA Expression Quantification) file formats. Auto-detects the
format based on column headers.

mRNA columns:  gene_name, gene_id, unstranded, tpm_unstranded, ...
miRNA columns: miRNA_ID, read_count, reads_per_million_miRNA_mapped

Usage:
    python -m tools.gdc_process --project_id TCGA-LIHC
    python -m tools.gdc_process --project_id TCGA-LIHC --metric tpm_unstranded
    python -m tools.gdc_process --project_id TCGA-LIHC --metric reads_per_million_miRNA_mapped
"""

import os
import argparse
import json
import pandas as pd
from typing import Dict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MRNA_METRICS = [
    "unstranded",
    "stranded_first",
    "stranded_second",
    "tpm_unstranded",
    "fpkm_unstranded",
    "fpkm_uq_unstranded",
]

MIRNA_METRICS = [
    "read_count",
    "reads_per_million_miRNA_mapped",
]

ALL_METRICS = MRNA_METRICS + MIRNA_METRICS


def _load_annotation(project_dir: str, project_id: str) -> pd.DataFrame:
    """Load the annotation file (file_id → tissue_type)."""
    annotation_file = os.path.join(project_dir, f"{project_id}_Annotation.txt")
    if not os.path.exists(annotation_file):
        raise FileNotFoundError(f"Annotation file not found: {annotation_file}")
    return pd.read_csv(annotation_file, sep="\t", index_col="file_id")


def _detect_format(tsv_path: str) -> str:
    """Detect whether a TSV file is mRNA or miRNA based on column headers."""
    df = pd.read_csv(tsv_path, sep="\t", comment="#", nrows=1)
    if "miRNA_ID" in df.columns:
        return "mirna"
    elif "gene_name" in df.columns:
        return "mrna"
    else:
        raise ValueError(
            f"Cannot detect format of {tsv_path}. "
            f"Columns: {list(df.columns)}"
        )


def _collect_expression_matrices(
    project_dir: str, annotation: pd.DataFrame, metric: str
) -> tuple[pd.DataFrame, str]:
    """Scan sample subdirectories and build a features × samples matrix.

    Returns (matrix, detected_format) where detected_format is 'mrna' or 'mirna'.
    """
    frames = []
    detected_format = None

    for file_id in os.listdir(project_dir):
        sample_dir = os.path.join(project_dir, file_id)
        if not os.path.isdir(sample_dir):
            continue

        # Find TSV or TXT quantification files
        data_files = [
            f for f in os.listdir(sample_dir)
            if f.endswith(".tsv") or f.endswith(".txt")
        ]
        if not data_files:
            continue

        file_path = os.path.join(sample_dir, data_files[0])

        try:
            df = pd.read_csv(file_path, sep="\t", comment="#")
        except Exception as e:
            print(f"   [WARN] Could not read {file_path}: {e}")
            continue

        # Detect format from first file
        if detected_format is None:
            if "miRNA_ID" in df.columns:
                detected_format = "mirna"
            elif "gene_name" in df.columns:
                detected_format = "mrna"
            else:
                print(f"   [WARN] Unknown format in {file_path}, skipping")
                continue

        # Process based on format
        if detected_format == "mrna":
            # Drop STAR summary rows (N_unmapped, N_multimapping, etc.)
            df = df[~df["gene_name"].str.startswith("N_")]
            id_col = "gene_name"
        else:  # mirna
            id_col = "miRNA_ID"

        if metric not in df.columns:
            raise ValueError(
                f"Metric '{metric}' not found in {file_path}. "
                f"Available columns: {list(df.columns)}. "
                f"Detected format: {detected_format}."
            )

        series = df.set_index(id_col)[metric].rename(file_id)
        frames.append(series)

    if not frames:
        raise RuntimeError(
            "No expression data found. Check that files are downloaded."
        )

    return pd.concat(frames, axis=1), detected_format


def process_gdc_data(
    project_id: str, metric: str = "tpm_unstranded"
) -> Dict[str, str]:
    """
    Combine downloaded GDC expression files into a matrix.

    Supports both mRNA and miRNA file formats. Auto-detects the format
    from column headers.

    Args:
        project_id: GDC project ID (e.g. 'TCGA-LIHC').
        metric:     Expression metric to extract.
                    mRNA options: unstranded, stranded_first, stranded_second,
                    tpm_unstranded, fpkm_unstranded, fpkm_uq_unstranded.
                    miRNA options: read_count, reads_per_million_miRNA_mapped.
                    Default: tpm_unstranded.

    Returns:
        Dict with keys: matrix_path, sample_sheet_path, gene_count,
        sample_count, data_format.

    Raises:
        FileNotFoundError: If the annotation file is missing.
        RuntimeError: If no expression data is found.
    """
    if metric not in ALL_METRICS:
        raise ValueError(
            f"Invalid metric '{metric}'. "
            f"mRNA metrics: {MRNA_METRICS}. miRNA metrics: {MIRNA_METRICS}."
        )

    project_dir = os.path.join(PROJECT_ROOT, "data", project_id, "raw")

    print(f"[GDC Process] Loading annotation for {project_id} ...")
    annotation = _load_annotation(project_dir, project_id)
    print(f"[GDC Process] {len(annotation)} samples found in annotation")

    print(f"[GDC Process] Building expression matrix (metric: {metric}) ...")
    matrix, data_format = _collect_expression_matrices(
        project_dir, annotation, metric
    )
    feature_count = matrix.shape[0]
    sample_count = matrix.shape[1]

    feature_label = "genes" if data_format == "mrna" else "miRNAs"
    print(
        f"[GDC Process] Matrix shape: {feature_count} {feature_label} "
        f"x {sample_count} samples (format: {data_format})"
    )

    # Write output
    processed_dir = os.path.join(PROJECT_ROOT, "data", project_id, "processed")
    os.makedirs(processed_dir, exist_ok=True)

    suffix = "ExpressionMatrix" if data_format == "mrna" else "miRNA_Matrix"
    matrix_path = os.path.join(processed_dir, f"{project_id}_{suffix}.tsv")
    matrix.to_csv(matrix_path, sep="\t")
    print(f"[GDC Process] Matrix saved → {matrix_path}")

    sample_sheet_path = os.path.join(
        processed_dir, f"{project_id}_SampleSheet.tsv"
    )
    sample_sheet = annotation.reindex(matrix.columns)
    sample_sheet.to_csv(sample_sheet_path, sep="\t")
    print(f"[GDC Process] Sample sheet → {sample_sheet_path}")

    return {
        "matrix_path": matrix_path,
        "sample_sheet_path": sample_sheet_path,
        "gene_count": str(feature_count),
        "sample_count": str(sample_count),
        "data_format": data_format,
    }


# --- CLI for Human Debugging ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Combine GDC expression files into a single matrix."
    )
    parser.add_argument(
        "--project_id", required=True,
        help="The GDC Project ID (e.g., TCGA-LIHC)",
    )
    parser.add_argument(
        "--metric", default="tpm_unstranded",
        choices=ALL_METRICS,
        help="Expression metric to extract (default: tpm_unstranded)",
    )
    args = parser.parse_args()

    info = process_gdc_data(args.project_id, args.metric)
    print(json.dumps(info, indent=2))

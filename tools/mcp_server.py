"""
MCP server exposing all 13 bioinformatic tools to Claude.

This is the second entry point for the bioinformatic agent. Instead of Gemini
orchestrating the tools (tools/main.py), here Claude acts as the orchestrator
via the Model Context Protocol.

The same pure-function tools are reused. Fetch tools include auto-dump so that
raw gene data is persisted to disk and the path is available for format_gene_list.

Usage
-----
Run the server (stdio transport, for Claude Code / Claude Desktop):
    python -m tools.mcp_server

Configure in Claude Code (.claude/settings.json):
    {
      "mcpServers": {
        "bioinformatic-agent": {
          "command": "/absolute/path/to/venv/.venv/bin/python",
          "args": ["-m", "tools.mcp_server"],
          "cwd": "/absolute/path/to/bioinfo_routing_agent"
        }
      }
    }
"""

import os
import json
import time
from typing import List, Dict

from mcp.server.fastmcp import FastMCP

from tools.ontology_mapper import map_term_to_ontology
from tools.quickgo_client import fetch_genes_by_go_term as _fetch_quickgo
from tools.kegg_client import fetch_genes_from_kegg as _fetch_kegg
from tools.reactome_client import fetch_genes_from_reactome as _fetch_reactome
from tools.msigdb_client import fetch_genes_from_msigdb as _fetch_msigdb
from tools.format_gene_list import format_gene_list
from tools.id_translator import translate_gene_ids
from tools.gdc_download import download_gdc_data
from tools.gdc_process import process_gdc_data
from tools.gdc_explore import explore_gdc_projects, explore_gdc_data_types
from tools.opentargets_client import query_opentargets, query_disease_genes

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

mcp = FastMCP("bioinformatic-agent")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


def _save_raw_dump(data, term: str, source: str) -> str:
    """Save raw gene data to data/<term>/raw/ and update index.json. Returns the file path."""
    safe_term = term.lower().replace(" ", "_").replace("/", "-").replace(":", "_")
    term_dir = os.path.join(PROJECT_ROOT, "data", safe_term)
    raw_dir = os.path.join(term_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(os.path.join(term_dir, "processed"), exist_ok=True)

    timestamp = int(time.time())
    filename = f"raw_{source}_{timestamp}.json"
    dump_path = os.path.join(raw_dir, filename)

    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    index_path = os.path.join(term_dir, "index.json")
    index_data = {"term": term, "files": []}
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except json.JSONDecodeError:
            pass

    index_data["files"].append({
        "raw_file": f"raw/{filename}",
        "source": source,
        "processed_files": [],
        "timestamp": timestamp,
    })

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)

    return dump_path


# ---------------------------------------------------------------------------
# Simple pass-through tools (no auto-dump needed)
# ---------------------------------------------------------------------------

mcp.add_tool(map_term_to_ontology)
mcp.add_tool(format_gene_list)
mcp.add_tool(translate_gene_ids)
mcp.add_tool(explore_gdc_projects)
mcp.add_tool(explore_gdc_data_types)
mcp.add_tool(download_gdc_data)
mcp.add_tool(process_gdc_data)
mcp.add_tool(query_opentargets)
mcp.add_tool(query_disease_genes)


# ---------------------------------------------------------------------------
# Fetch tools — wrapped to add auto-dump
# The full gene list is returned to Claude (no token-summary truncation needed
# since MCP does not have the same context-window pressure as the LLM loop).
# raw_dump_path is included so Claude can pass it to format_gene_list.
# ---------------------------------------------------------------------------

@mcp.tool()
def fetch_genes_by_go_term(go_id: str) -> dict:
    """
    Fetch genes annotated to a GO term from QuickGO (manual evidence only, no IEA).
    Saves raw data to disk and returns the path alongside the gene list.

    Args:
        go_id: GO term ID (e.g. 'GO:0006096').

    Returns:
        dict with keys: gene_count, genes (list of dicts), raw_dump_path.
    """
    result = _fetch_quickgo(go_id)
    dump_path = _save_raw_dump(result, go_id, "quickgo")
    return {"gene_count": len(result), "genes": result, "raw_dump_path": dump_path}


@mcp.tool()
def fetch_genes_from_kegg(biology_term: str, organism: str = "hsa") -> dict:
    """
    Fetch genes from KEGG pathways matching a biological term.
    Saves raw data to disk and returns the path alongside the gene list.

    Args:
        biology_term: Human-readable biological process (e.g. 'glycolysis').
                      Use the label returned by map_term_to_ontology, not the GO ID.
        organism:     KEGG organism code (default 'hsa' = Homo sapiens).

    Returns:
        dict with keys: gene_count, genes (list of dicts), raw_dump_path.
    """
    result = _fetch_kegg(biology_term, organism)
    dump_path = _save_raw_dump(result, biology_term, "kegg")
    return {"gene_count": len(result), "genes": result, "raw_dump_path": dump_path}


@mcp.tool()
def fetch_genes_from_reactome(biology_term: str) -> dict:
    """
    Fetch genes from Reactome pathways matching a biological term.
    Saves raw data to disk and returns the path alongside the gene list.

    Args:
        biology_term: Human-readable biological process (e.g. 'glycolysis').
                      Use the label returned by map_term_to_ontology, not the GO ID.

    Returns:
        dict with keys: gene_count, genes (list of dicts), raw_dump_path.
    """
    result = _fetch_reactome(biology_term)
    dump_path = _save_raw_dump(result, biology_term, "reactome")
    return {"gene_count": len(result), "genes": result, "raw_dump_path": dump_path}


@mcp.tool()
def fetch_genes_from_msigdb(biology_term: str, collection: str = "H") -> dict:
    """
    Fetch genes from MSigDB gene sets matching a biological term.
    Saves raw data to disk and returns the path alongside the gene list.

    Args:
        biology_term: Human-readable biological process (e.g. 'glycolysis').
        collection:   MSigDB collection code. H=Hallmark (default), C2=curated,
                      C5=GO, C6=oncogenic, C7=immunologic.

    Returns:
        dict with keys: gene_count, genes (list of dicts), raw_dump_path.
    """
    result = _fetch_msigdb(biology_term, collection)
    dump_path = _save_raw_dump(result, biology_term, "msigdb")
    return {"gene_count": len(result), "genes": result, "raw_dump_path": dump_path}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _load_env()
    mcp.run()  # stdio transport — required for Claude Code / Claude Desktop

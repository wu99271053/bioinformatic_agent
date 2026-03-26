# Bioinformatic Agent

Routes natural-language biology queries across 5 databases (KEGG, Reactome, MSigDB, QuickGO, GDC) and retrieves curated gene lists.

> **Developing?** Load the full development brain: *"read .private/CLAUDE.dev.md"*

---

## Two Orchestration Modes

| Mode | Orchestrator | Entry point | API key |
|------|-------------|-------------|---------|
| **Gemini agent** | Gemini 2.5 Flash (manual ReAct loop) | `python -m tools.main` | `GOOGLE_API_KEY` in `.env` |
| **MCP server** | Claude (Model Context Protocol) | `python -m tools.mcp_server` | none |

---

## Tools (13)

### Gene Retrieval

| Tool | Function | Input | Source |
|------|----------|-------|--------|
| `ontology_mapper.py` | `map_term_to_ontology` | `biology_term` | EBI OLS |
| `quickgo_client.py` | `fetch_genes_by_go_term` | `go_id` | QuickGO |
| `kegg_client.py` | `fetch_genes_from_kegg` | `biology_term` | KEGG |
| `reactome_client.py` | `fetch_genes_from_reactome` | `biology_term` | Reactome |
| `msigdb_client.py` | `fetch_genes_from_msigdb` | `biology_term`, `collection` | MSigDB |

### Post-Processing

| Tool | Function | Input |
|------|----------|-------|
| `format_gene_list.py` | `format_gene_list` | `input_path` (raw JSON) |
| `id_translator.py` | `translate_gene_ids` | `gene_ids`, `to_format` |

### Gene ↔ Disease

| Tool | Function | Input |
|------|----------|-------|
| `opentargets_client.py` | `query_opentargets` | `gene_symbols`, `disease_filter` |
| `opentargets_client.py` | `query_disease_genes` | `disease_term`, `gene_list` |

### GDC

| Tool | Function | Input |
|------|----------|-------|
| `gdc_explore.py` | `explore_gdc_projects` | `keyword` |
| `gdc_explore.py` | `explore_gdc_data_types` | `project_id` |
| `gdc_download.py` | `download_gdc_data` | `project_id`, `data_type` |
| `gdc_process.py` | `process_gdc_data` | `project_id`, `metric` |

---

## Quick Reference

```bash
# Activate environment
source venv/.venv/bin/activate

# Gemini agent
python -m tools.main
python -m tools.main --model gemini-2.0-flash

# MCP server (stdio)
python -m tools.mcp_server

# Test individual tools
python -m tools.ontology_mapper --term "glycolysis"
python -m tools.quickgo_client --go_id GO:0006096
python -m tools.kegg_client --biology_term glycolysis
python -m tools.reactome_client --biology_term glycolysis
python -m tools.msigdb_client --biology_term glycolysis
python -m tools.gdc_explore --keyword liver
python -m tools.gdc_download --project_id TCGA-LIHC --metadata_only
python -m tools.id_translator --ids "UniProtKB:P04818,UniProtKB:P11586"
python -m tools.format_gene_list --input data/<term>/raw/<file>.json
```

### MCP setup (Claude Code)

Add to `.claude/settings.json`:
```json
{
  "mcpServers": {
    "bioinformatic-agent": {
      "command": "/abs/path/to/venv/.venv/bin/python",
      "args": ["-m", "tools.mcp_server"],
      "cwd": "/abs/path/to/bioinfo_routing_agent"
    }
  }
}
```

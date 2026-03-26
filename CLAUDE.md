# Bioinformatic Agent — Project Manual

> **Read this first.** This document is the developer's architecture guide. For the Claude Skills-standard agent behavior definition, see [`SKILL.md`](SKILL.md).

> **Resuming work?** Read `doc/development_log.md` for the full iteration history — every past conversation is logged there in Input/Problem/Output format. Check the Roadmap section below for open tasks.

---

## What This Project Is

A bioinformatic routing agent with **two orchestration modes** sharing the same 13 pure-function tools:

| Mode | Orchestrator | Entry point | API key needed |
|------|-------------|-------------|----------------|
| **Gemini agent** | Gemini 2.5 Flash (manual ReAct loop) | `python -m tools.main` | `GOOGLE_API_KEY` in `.env` |
| **MCP server** | Claude (via Model Context Protocol) | `python -m tools.mcp_server` | none (tools are local) |

The agent interprets natural-language queries about biological processes, maps them to the right databases (QuickGO, KEGG, Reactome, MSigDB, GDC), and retrieves gene lists.

---

## Project Structure

```
bioinformatic_agent/
├── CLAUDE.md                ← THIS FILE — project brain
├── README.md                ← human-facing quickstart
├── .env                     ← GOOGLE_API_KEY (gitignored)
├── .gitignore
│
├── tools/                   ← all agent tools + orchestrator
│   ├── main.py              ← Gemini orchestrator (manual ReAct loop)
│   ├── mcp_server.py        ← MCP server (Claude orchestrates the same tools)
│   ├── ontology_mapper.py   ← term → GO ID candidates (EBI OLS)
│   ├── quickgo_client.py    ← GO ID → genes (QuickGO, manual evidence only)
│   ├── kegg_client.py       ← term → genes (KEGG pathways → UniProt)
│   ├── reactome_client.py   ← term → genes (Reactome pathways → UniProt)
│   ├── msigdb_client.py     ← term → genes (MSigDB gene sets, GMT files)
│   ├── format_gene_list.py  ← raw JSON dump → CSV (agent-discretion)
│   ├── id_translator.py     ← UniProt → Entrez/Symbol/Ensembl (MyGene.info)
│   ├── gdc_download.py      ← GDC Portal RNA-Seq download + metadata
│   └── gdc_process.py       ← combine per-sample TSVs → expression matrix
│
├── data/                    ← all output data (gitignored)
│   ├── .msigdb_cache/       ← cached MSigDB GMT files
│   └── <term>/              ← per-query directories
│       ├── raw/             ← timestamped JSON dumps
│       ├── processed/       ← CSVs, expression matrices
│       └── index.json       ← raw → processed file mapping
│
├── doc/                     ← documentation
│   ├── system_prompt.md     ← LLM system instruction (loaded by main.py)
│   ├── schemas.json         ← OpenAPI schemas for all 9 tools
│   └── development_log.md   ← iteration-by-iteration build history
│
└── venv/                    ← UV-managed virtual environment (Python 3.13)
```

---

## Tools Reference (13 tools)

### Gene Retrieval Pipeline

| Tool | Function | Input | Output | Source |
|------|----------|-------|--------|--------|
| `ontology_mapper.py` | `map_term_to_ontology` | `biology_term` | GO ID candidates `[{id, label}]` | EBI OLS |
| `quickgo_client.py` | `fetch_genes_by_go_term` | `go_id` | UniProtKB genes (manual evidence, no IEA) | QuickGO |
| `kegg_client.py` | `fetch_genes_from_kegg` | `biology_term` | UniProtKB IDs via pathway → gene → UniProt | KEGG |
| `reactome_client.py` | `fetch_genes_from_reactome` | `biology_term` | UniProtKB IDs from pathway participants | Reactome |
| `msigdb_client.py` | `fetch_genes_from_msigdb` | `biology_term`, `collection` | HGNC gene symbols from gene sets | MSigDB (Broad) |

### Post-Processing

| Tool | Function | Input | Output |
|------|----------|-------|--------|
| `format_gene_list.py` | `format_gene_list` | `input_path` (raw JSON) | CSV in `processed/` |
| `id_translator.py` | `translate_gene_ids` | `gene_ids`, `to_format` | ID mappings via MyGene.info |

### Gene ↔ Disease Bridge

| Tool | Function | Input | Output |
|------|----------|-------|--------|
| `opentargets_client.py` | `query_opentargets` | `gene_symbols`, `disease_filter` | gene → diseases (small lookups) |
| `opentargets_client.py` | `query_disease_genes` | `disease_term`, `gene_list` | disease → genes + intersection (PREFERRED) |

### GDC Data

| Tool | Function | Input | Output |
|------|----------|-------|--------|
| `gdc_explore.py` | `explore_gdc_projects` | `keyword` | matching projects + data categories |
| `gdc_explore.py` | `explore_gdc_data_types` | `project_id` | data types with file counts |
| `gdc_download.py` | `download_gdc_data` | `project_id`, `data_type` | metadata + manifest + data files |
| `gdc_process.py` | `process_gdc_data` | `project_id`, `metric` | expression matrix (mRNA or miRNA) |

---

## Development Conventions

### Tool Design Rules
1. **Pure Python functions** — deterministic, testable in isolation, no LLM dependency
2. **Fail-fast** — raise `ValueError` on bad input or empty results; never swallow errors
3. **CLI block** — every tool has an `if __name__ == "__main__":` block with `argparse` for standalone testing
4. **Consistent return format** — gene fetch tools return `List[Dict]` with keys: `gene_id`, `gene_symbol`, `description`, `evidence_used`
5. **Auto-dump** — `main.py` automatically saves raw results to `data/<term>/raw/raw_<source>_<timestamp>.json`

### CLI vs Agent Behavior
- **CLI mode** (`python -m tools.<tool> --args`): the tool **prints** JSON to stdout and exits. No files are saved to disk. This is for human debugging and quick testing.
- **Agent mode** (`python -m tools.main`): when the agent calls a fetch tool, `main.py`'s orchestrator automatically intercepts the result and saves it via `save_raw_dump()`. The `raw_dump_path` is included in the function response so the agent can later call `format_gene_list` on it.

This separation is intentional — tools are pure functions that return data; the orchestrator handles persistence.

### Logging Development Work
After each development session, append an entry to `doc/development_log.md` using this format:
```
**Input:** <what the user asked for>
**Problem_identifying:** <why it wasn't trivial — what was broken, missing, or misunderstood>
**Output:** <what was changed and why>
```
This log is the project's institutional memory. Future sessions should read it for context.

### Key Patterns in `main.py`
- `TOOL_MAP` — maps function names to Python callables
- `FETCH_TOOLS` — set of tool names that return gene lists (triggers auto-dump)
- `SOURCE_LABELS` — maps tool names to source labels for filenames
- Manual function-calling loop with `AutomaticFunctionCallingConfig(disable=True)`
- `save_raw_dump()` — writes raw data + updates `index.json`

### Dependencies
- `google-genai` — Gemini API client
- `requests` — HTTP calls to external APIs
- `pandas` — GDC expression matrix processing
- Managed via UV (`venv/pyproject.toml`)

---

## Data Flow

```
User query ("glycolysis")
    │
    ▼
map_term_to_ontology → GO:0006096 + label "glycolytic process"
    │
    ├─► fetch_genes_by_go_term(GO:0006096)     → data/<term>/raw/raw_quickgo_<ts>.json
    ├─► fetch_genes_from_kegg("glycolysis")     → data/<term>/raw/raw_kegg_<ts>.json
    ├─► fetch_genes_from_reactome("glycolysis") → data/<term>/raw/raw_reactome_<ts>.json
    └─► fetch_genes_from_msigdb("glycolysis")   → data/<term>/raw/raw_msigdb_<ts>.json
            │
            ▼
    format_gene_list (optional) → data/<term>/processed/<name>.csv
    translate_gene_ids (optional) → normalise IDs across sources
```

---

## Roadmap

### Completed
- [x] Term disambiguation (OLS), QuickGO, KEGG, Reactome fetchers
- [x] CSV formatter, ID translator (MyGene.info)
- [x] MSigDB client (GMT download, caching, keyword search)
- [x] GDC download + process integration
- [x] Manual function-calling loop with real-time output
- [x] Per-term data directory with `index.json` tracking
- [x] System prompt with anti-hallucination rules

### Open
- [ ] Add `--verbose` flag to suppress `[Reasoning]` blocks when output is piped
- [ ] Persist conversation history to disk for cross-session resumption
- [ ] Graceful Gemini API backoff on rate limit errors
- [ ] Cross-source gene deduplication tool
- [ ] Add few-shot examples to system prompt for better GO ID selection
- [ ] OpenTargets integration (disease → gene associations, free GraphQL API)
- [ ] Multi-ontology support (MeSH, HPO, ChEBI)
- [ ] Web interface (FastAPI wrapper)
- [ ] Confidence scoring on GO ID candidates
- [ ] Batch processor for unprocessed `index.json` entries

---

## Quick Reference

```bash
# Activate environment
source venv/.venv/bin/activate

# --- Gemini agent (Gemini orchestrates tools) ---
python -m tools.main
python -m tools.main --model gemini-2.0-flash

# --- MCP server (Claude orchestrates tools) ---
# Run directly (stdio):
python -m tools.mcp_server

# Configure in Claude Code — add to .claude/settings.json:
# {
#   "mcpServers": {
#     "bioinformatic-agent": {
#       "command": "/abs/path/to/venv/.venv/bin/python",
#       "args": ["-m", "tools.mcp_server"],
#       "cwd": "/abs/path/to/bioinformatic_agent"
#     }
#   }
# }

# Test individual tools
python -m tools.ontology_mapper --term "glycolysis"
python -m tools.quickgo_client --go_id GO:0006096
python -m tools.kegg_client --biology_term glycolysis
python -m tools.reactome_client --biology_term glycolysis
python -m tools.msigdb_client --biology_term glycolysis
python -m tools.msigdb_client --biology_term apoptosis --collection C2
python -m tools.gdc_download --project_id TCGA-LIHC --metadata_only
python -m tools.id_translator --ids "UniProtKB:P04818,UniProtKB:P11586"
python -m tools.format_gene_list --input data/<term>/raw/<file>.json
```

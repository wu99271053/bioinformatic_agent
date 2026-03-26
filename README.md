# Data Retrieval Agent

An AI-powered routing agent that interprets biological queries and retrieves gene lists from multiple databases (QuickGO, KEGG, Reactome, MSigDB) with support for GDC RNA-Seq data download and processing.

## Quickstart

```bash
# Activate environment
source venv/.venv/bin/activate

# Set API key
echo "GOOGLE_API_KEY=your_key_here" > .env

# Download GDC Client (Required for GDC Data Download)
# Download from: https://gdc.cancer.gov/access-data/gdc-data-transfer-tool
# Extract the binary and place it at: tools/gdc-client

# Run the agent
python -m tools.main
```

## Tools

| Tool | Source | Returns |
|------|--------|---------|
| `ontology_mapper` | EBI OLS | GO ID candidates |
| `quickgo_client` | QuickGO | Genes (manual evidence, UniProtKB) |
| `kegg_client` | KEGG | Genes (pathway-linked, UniProtKB) |
| `reactome_client` | Reactome | Genes (pathway participants, UniProtKB) |
| `msigdb_client` | MSigDB | Genes (curated gene sets, HGNC symbols) |
| `format_gene_list` | Local | Raw JSON → CSV |
| `id_translator` | MyGene.info | UniProt → Entrez/Symbol/Ensembl |
| `gdc_download` | GDC Portal | RNA-Seq metadata + data files |
| `gdc_process` | Local | Expression matrix (genes × samples) |

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — full project manual (architecture, conventions, roadmap)
- **[doc/system_prompt.md](doc/system_prompt.md)** — LLM system instruction
- **[doc/schemas.json](doc/schemas.json)** — tool schemas

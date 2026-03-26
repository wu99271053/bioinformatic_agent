# Demo

Sample queries and pre-fetched output — no API key needed to browse results.

## Try the agent

```bash
source venv/.venv/bin/activate
python -m tools.main
```

Then paste any query from `queries.txt`.

## Pre-fetched output

| File | Query | Source |
|------|-------|--------|
| `sample_output/glycolysis_kegg.json` | "Find genes in glycolysis" | KEGG pathway hsa00010 |
| `sample_output/glycolysis_genes.csv` | Same — formatted CSV | via `format_gene_list` |

## Without an API key

Browse `sample_output/` directly to see the agent's output format:
- **JSON** (`*_kegg.json`) — raw dump saved by the orchestrator, one object per gene
- **CSV** (`*_genes.csv`) — post-processed by `format_gene_list.py`

Each gene entry has four fields: `gene_id`, `gene_symbol`, `description`, `evidence_used`.

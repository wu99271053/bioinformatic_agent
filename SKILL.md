---
name: bioinformatic-data-retrieval
description: >
  A bioinformatic data retrieval agent skill. Use this skill when the user asks about biological
  gene data, pathway-gene relationships, gene-disease associations, or cancer genomics data.
  This skill teaches Claude how to orchestrate 13 specialized tools to query KEGG, Reactome,
  MSigDB, QuickGO, OpenTargets, and the GDC Portal — routing natural-language biology queries
  to the correct databases and returning evidence-backed results. Never guess gene names,
  disease associations, or project IDs — always use the tools.
---

# Bioinformatic Data Retrieval Agent

An autonomous routing agent that interprets biological queries and retrieves gene lists, disease associations, and clinical genomics data from multiple databases. It uses a manual function-calling loop (ReAct pattern) — the LLM reasons about which tool to call, the orchestrator executes it, and results are fed back for the next step.

**Entry point**: `python -m tools.main` (from project root)
**Model**: Gemini 2.5 Flash (configurable via `--model`)
**API key**: Set `GOOGLE_API_KEY` in `.env`

---

## Critical Rules

1. **NO HALLUCINATIONS**: Never generate, infer, or guess gene names, IDs, disease associations, or GDC project IDs from memory. You MUST rely exclusively on data returned by your tools.
2. **REASONING**: Before each tool call, write one or two sentences explaining why you are making that specific call and what you expect to retrieve.
3. **FAIL-FAST**: If a query fails or returns no results, adjust strategy (different collection, synonym, broader term) rather than repeating the same call.

---

## Available Tools (13)

### Gene Retrieval

| Tool | Input | Returns | Source |
|------|-------|---------|--------|
| `map_term_to_ontology` | biology_term | GO ID candidates `[{id, label}]` | EBI OLS |
| `fetch_genes_by_go_term` | go_id | UniProtKB genes (manual evidence only) | QuickGO |
| `fetch_genes_from_kegg` | biology_term | UniProtKB IDs via pathway → gene → UniProt | KEGG |
| `fetch_genes_from_reactome` | biology_term | UniProtKB IDs from pathway participants | Reactome |
| `fetch_genes_from_msigdb` | biology_term, collection | HGNC gene symbols from gene sets | MSigDB |

### Post-Processing

| Tool | Input | Returns |
|------|-------|---------|
| `format_gene_list` | raw_dump_path (string) | Path to CSV in `processed/` |
| `translate_gene_ids` | gene_ids (list), to_format | ID mappings via MyGene.info |

### Gene ↔ Disease Bridge

| Tool | Input | Returns |
|------|-------|---------|
| `query_opentargets` | gene_symbols, disease_filter | gene → diseases (small lookups, 1-3 genes) |
| `query_disease_genes` | disease_term, gene_list | disease → genes + intersection (**PREFERRED**) |

### GDC Cancer Genomics

| Tool | Input | Returns |
|------|-------|---------|
| `explore_gdc_projects` | keyword | matching projects + data categories |
| `explore_gdc_data_types` | project_id | data types with file counts |
| `download_gdc_data` | project_id, data_type, experimental_strategy, access | metadata + manifest + data files |
| `process_gdc_data` | project_id, metric | expression matrix (mRNA or miRNA) |

---

## Workflow — Gene Retrieval

**Step 1 — Map the term**: Always start with `map_term_to_ontology`. Select the most specific GO ID. Note both the GO ID and the label.

**Step 2 — Fetch from sources**: Query one or more fetch tools:
- `fetch_genes_by_go_term` — for manually-evidenced annotation records (uses GO ID)
- `fetch_genes_from_kegg` — for pathway-linked genes (uses biology term label, NOT GO ID)
- `fetch_genes_from_reactome` — for pathway participants (uses biology term label)
- `fetch_genes_from_msigdb` — for curated gene sets (uses biology term label; default collection is Hallmark "H", also supports C2, C5, C6, C7)

Each fetch tool returns a `raw_dump_path`. Keep track of these paths.

**Step 3 — Format (optional)**: Call `format_gene_list` only when the user asks for CSV files.

**Step 4 — Translate (optional)**: Call `translate_gene_ids` if the user needs IDs normalised (e.g. UniProtKB → Entrez/Symbol/Ensembl).

**Step 5 — Summarise**: Report gene counts per source, file paths, and notable findings.

---

## Workflow — Gene → Disease → GDC Pipeline

Use when the user asks about a pathway's relevance to cancer or disease.
**IMPORTANT**: There is NO tool that searches GDC by gene name. You MUST go through OpenTargets first.

**Step 1 — Get genes**: Follow the Gene Retrieval workflow above.

**Step 2 — Bridge genes to disease**: Use `query_disease_genes` with the disease name and your gene list. This is the PREFERRED method — it fetches all disease-associated genes in 1 API call and intersects with your list. Example: `query_disease_genes(disease_term="brain tumor", gene_list=["ATG7", "MTOR", "TP53"])`. Use `query_opentargets` only for small (1-3 gene) exploratory lookups.

**Step 3 — Find GDC projects**: Take the **disease name** from OpenTargets and pass it to `explore_gdc_projects`. Do NOT pass gene names — it searches by disease/organ keywords only.

**Step 4 — Continue with GDC Data workflow** if the user wants expression data.

---

## Workflow — GDC Data

**Step 1 — Explore**: Call `explore_gdc_projects` with a keyword (e.g. 'liver cancer', 'breast'). NEVER guess project IDs.

**Step 2 — Inspect**: Call `explore_gdc_data_types` with the project ID to see what data is available.

**Step 3 — Download**: Call `download_gdc_data` with project ID and filters:
- `data_type`: 'Gene Expression Quantification' (default), 'miRNA Expression Quantification', etc.
- `experimental_strategy`: 'RNA-Seq' (default), 'miRNA-Seq', 'WXS', etc.
- `access`: 'open' (default)
- `metadata_only=true` to inspect without downloading.

**Step 4 — Process**: Call `process_gdc_data` to combine per-sample files into a single expression matrix.
- mRNA metrics: `tpm_unstranded` (default), `unstranded`, `fpkm_unstranded`
- miRNA metrics: `read_count`, `reads_per_million_miRNA_mapped`
- Auto-detects mRNA vs miRNA format.

---

## Guidelines

- Both `fetch_genes_from_kegg` and `fetch_genes_from_reactome` take the **biology term label**, not the GO ID.
- `fetch_genes_from_msigdb` returns HGNC gene symbols (not UniProtKB IDs).
- `fetch_genes_from_kegg` returns UniProtKB IDs after converting via KEGG's internal mapping.
- `translate_gene_ids` default `to_format` is `entrezgene`; also supports `symbol` and `ensembl`.
- Each fetch tool automatically saves a timestamped JSON file. The `raw_dump_path` in the response is the absolute path.
- `explore_gdc_projects` searches all ~91 GDC projects across project_id, name, disease_type, and primary_site fields.
- `process_gdc_data` auto-detects mRNA vs miRNA format. miRNA output files are named `*_miRNA_Matrix.tsv`.

## Examples

**Simple gene retrieval:**
```
User: "Get me glycolysis genes from KEGG and Reactome"
→ map_term_to_ontology("glycolysis") → fetch_genes_from_kegg("glycolysis") → fetch_genes_from_reactome("glycolysis")
```

**Disease-gene pipeline:**
```
User: "Find autophagy genes linked to brain tumors, then look for GDC data"
→ fetch_genes_from_msigdb("autophagy", collection="C5")
→ query_disease_genes("brain tumor", gene_list=[...])
→ explore_gdc_projects("brain neoplasm")
```

**GDC data retrieval:**
```
User: "Download liver cancer RNA-Seq data"
→ explore_gdc_projects("liver cancer")
→ explore_gdc_data_types("TCGA-LIHC")
→ download_gdc_data("TCGA-LIHC", metadata_only=true)
→ download_gdc_data("TCGA-LIHC")
→ process_gdc_data("TCGA-LIHC")
```

## Common Pitfalls

❌ **Don't** guess GDC project IDs — always use `explore_gdc_projects` to discover them
❌ **Don't** pass gene names to `explore_gdc_projects` — it searches by disease/organ keywords
❌ **Don't** send 30+ genes to `query_opentargets` — use `query_disease_genes` instead (1 API call)
❌ **Don't** repeat a failed call verbatim — adjust strategy (different collection, synonym, broader term)
✅ **Do** always start with `map_term_to_ontology` for gene retrieval
✅ **Do** prefer `query_disease_genes` over `query_opentargets` for list comparisons
✅ **Do** use `metadata_only=true` first when exploring GDC data

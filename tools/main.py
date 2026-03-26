import os
import json
import time
import argparse
from google import genai
from google.genai import types

from tools.ontology_mapper import map_term_to_ontology
from tools.quickgo_client import fetch_genes_by_go_term
from tools.kegg_client import fetch_genes_from_kegg
from tools.reactome_client import fetch_genes_from_reactome
from tools.msigdb_client import fetch_genes_from_msigdb
from tools.format_gene_list import format_gene_list
from tools.id_translator import translate_gene_ids
from tools.gdc_download import download_gdc_data
from tools.gdc_process import process_gdc_data
from tools.gdc_explore import explore_gdc_projects, explore_gdc_data_types
from tools.opentargets_client import query_opentargets, query_disease_genes

DEFAULT_MODEL = "gemini-2.5-flash"

TOOL_MAP = {
    "map_term_to_ontology": map_term_to_ontology,
    "fetch_genes_by_go_term": fetch_genes_by_go_term,
    "fetch_genes_from_kegg": fetch_genes_from_kegg,
    "fetch_genes_from_reactome": fetch_genes_from_reactome,
    "fetch_genes_from_msigdb": fetch_genes_from_msigdb,
    "format_gene_list": format_gene_list,
    "translate_gene_ids": translate_gene_ids,
    "download_gdc_data": download_gdc_data,
    "process_gdc_data": process_gdc_data,
    "explore_gdc_projects": explore_gdc_projects,
    "explore_gdc_data_types": explore_gdc_data_types,
    "query_opentargets": query_opentargets,
    "query_disease_genes": query_disease_genes,
}

FETCH_TOOLS = {"fetch_genes_by_go_term", "fetch_genes_from_kegg", "fetch_genes_from_reactome", "fetch_genes_from_msigdb"}

SOURCE_LABELS = {
    "fetch_genes_by_go_term": "quickgo",
    "fetch_genes_from_kegg": "kegg",
    "fetch_genes_from_reactome": "reactome",
    "fetch_genes_from_msigdb": "msigdb",
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    env_path = os.path.join(PROJECT_ROOT, '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key] = val


def load_system_prompt():
    prompt_path = os.path.join(PROJECT_ROOT, 'doc', 'system_prompt.md')
    if os.path.exists(prompt_path):
        with open(prompt_path, 'r') as f:
            return f.read()
    return "You are a highly capable Bioinformatic Routing Agent."


def save_raw_dump(data, term, source) -> str:
    """Save a raw gene dump under data/<term>/raw/ and update data/<term>/index.json.
    Returns the absolute path of the written file.
    """
    safe_term = term.lower().replace(' ', '_').replace('/', '-')
    term_dir = os.path.join(PROJECT_ROOT, "data", safe_term)
    raw_dir = os.path.join(term_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(os.path.join(term_dir, "processed"), exist_ok=True)

    timestamp = int(time.time())
    raw_filename = f"raw_{source}_{timestamp}.json"
    dump_path = os.path.join(raw_dir, raw_filename)

    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n[Data Dump] Saved → {dump_path}")

    index_path = os.path.join(term_dir, "index.json")
    index_data = {"term": term, "files": []}
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except json.JSONDecodeError:
            pass

    index_data["files"].append({
        "raw_file": f"raw/{raw_filename}",
        "source": source,
        "processed_files": [],
        "timestamp": timestamp,
    })

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)

    return dump_path


def run_turn(client, config, model, user_input, conversation_history):
    """
    Run one user turn through a manual function-calling loop.
    Appends all model and tool-response messages to conversation_history in-place.
    """
    conversation_history.append(
        types.Content(role="user", parts=[types.Part(text=user_input)])
    )

    term_used = None

    while True:
        response = client.models.generate_content(
            model=model,
            config=config,
            contents=conversation_history,
        )

        model_content = response.candidates[0].content

        # Guard against empty/filtered model responses
        if model_content is None or not model_content.parts:
            print("\n[Agent] (model returned empty response — may be a token limit or safety filter)")
            break

        conversation_history.append(model_content)

        fn_calls = [
            p.function_call
            for p in model_content.parts
            if hasattr(p, 'function_call') and p.function_call
        ]

        if not fn_calls:
            # Final answer — print once
            final_text = "".join(p.text for p in model_content.parts if p.text)
            if final_text.strip():
                print(f"\nAgent: {final_text.strip()}")
            break

        # Mid-loop reasoning (text alongside tool calls)
        for part in model_content.parts:
            if part.text:
                print(f"\n[Reasoning]\n{part.text.strip()}")

        response_parts = []
        for fc in fn_calls:
            call_args = dict(fc.args)
            print(f"\n[Tool Call] {fc.name}({call_args})")

            fn = TOOL_MAP.get(fc.name)
            if fn is None:
                result = {"error": f"Unknown tool: {fc.name}"}
                print(f"[Tool Error] {result['error']}")
                response_parts.append(
                    types.Part(function_response=types.FunctionResponse(
                        name=fc.name, response={"result": result}
                    ))
                )
                continue

            try:
                result = fn(**call_args)

                if fc.name == "map_term_to_ontology":
                    term_used = call_args.get("biology_term", "unknown")
                    print(f"[GO Terms Found]")
                    for item in result:
                        print(f"  {item['id']}  {item['label']}")
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result}
                        ))
                    )

                elif fc.name in FETCH_TOOLS:
                    source_label = SOURCE_LABELS[fc.name]
                    gene_count = len(result) if isinstance(result, list) else 0
                    print(f"[{source_label.upper()} Genes Fetched] {gene_count} genes")
                    # Fallback: derive term from call args if ontology mapping was skipped
                    if term_used is None:
                        term_used = (
                            call_args.get("biology_term")
                            or call_args.get("go_id", "unknown")
                        )
                    dump_path = None
                    if term_used:
                        dump_path = save_raw_dump(result, term_used, source_label)

                    # Send only a summary back to the LLM to save tokens.
                    # Full data is already saved to disk via save_raw_dump().
                    if isinstance(result, list) and gene_count > 0:
                        # Extract gene symbols for the summary
                        symbols = [
                            r.get("gene_symbol") or r.get("gene_id", "?")
                            for r in result
                        ]
                        # Show first 2 + last 2 as a preview
                        if gene_count <= 6:
                            sample = symbols
                        else:
                            sample = symbols[:2] + ["..."] + symbols[-2:]

                        # Cap symbols sent to LLM (for use in follow-up tools)
                        MAX_SYMBOLS = 10
                        truncated = len(symbols) > MAX_SYMBOLS
                        summary = {
                            "gene_count": gene_count,
                            "sample_gene_symbols": sample,
                            "gene_symbols": symbols[:MAX_SYMBOLS],
                            "symbols_truncated": truncated,
                            "raw_dump_path": dump_path,
                        }
                    else:
                        summary = {
                            "gene_count": 0,
                            "raw_dump_path": dump_path,
                        }

                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": summary},
                        ))
                    )

                elif fc.name == "format_gene_list":
                    print(f"[CSV Written] {result}")
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result}
                        ))
                    )

                elif fc.name == "translate_gene_ids":
                    print(f"[ID Translation] {len(result)} mappings returned")
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result}
                        ))
                    )

                elif fc.name == "download_gdc_data":
                    print(f"[GDC Download] {result.get('file_count', '?')} files for {result.get('project_id')}")
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result}
                        ))
                    )

                elif fc.name == "process_gdc_data":
                    print(f"[GDC Process] {result.get('gene_count', '?')} genes x {result.get('sample_count', '?')} samples")
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result}
                        ))
                    )

                elif fc.name == "query_opentargets":
                    count = len(result) if isinstance(result, list) else 0
                    print(f"[OpenTargets gene→disease] {count} associations returned")
                    dump_term = term_used or "opentargets"
                    dump_path = save_raw_dump(result, dump_term, "opentargets_gene2disease")
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result, "raw_dump_path": dump_path}
                        ))
                    )

                elif fc.name == "query_disease_genes":
                    int_count = result.get("intersection_count", "?")
                    input_count = result.get("input_gene_count", "?")
                    disease = result.get("disease_name", "?")
                    print(f"[OpenTargets disease→genes] {int_count}/{input_count} genes overlap with {disease}")
                    dump_term = term_used or result.get("disease_name", "opentargets").lower().replace(" ", "_")
                    dump_path = save_raw_dump(result, dump_term, "opentargets_disease2gene")
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result, "raw_dump_path": dump_path}
                        ))
                    )

                else:
                    response_parts.append(
                        types.Part(function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result}
                        ))
                    )

            except Exception as e:
                print(f"[Tool Error / Fail-Fast] {e}")
                response_parts.append(
                    types.Part(function_response=types.FunctionResponse(
                        name=fc.name, response={"error": str(e)}
                    ))
                )

        conversation_history.append(
            types.Content(role="user", parts=response_parts)
        )


def main():
    parser = argparse.ArgumentParser(description="Bio-Routing Agent")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Gemini model ID to use (default: {DEFAULT_MODEL})"
    )
    args = parser.parse_args()

    print(f"Bio-Routing Agent is starting... (model: {args.model})")
    load_env()

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        print("Error: GOOGLE_API_KEY is not set correctly in the .env file.")
        return

    client = genai.Client(api_key=api_key)
    system_instruction = load_system_prompt()

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.0,
        tools=[
            map_term_to_ontology,
            fetch_genes_by_go_term,
            fetch_genes_from_kegg,
            fetch_genes_from_reactome,
            fetch_genes_from_msigdb,
            format_gene_list,
            translate_gene_ids,
            download_gdc_data,
            process_gdc_data,
            explore_gdc_projects,
            explore_gdc_data_types,
            query_opentargets,
            query_disease_genes,
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    conversation_history = []

    print("Agent is ready! Type 'exit' to quit.")
    print("-" * 50)

    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ['exit', 'quit']:
            print("Shutting down Bio-Routing Agent. Goodbye!")
            break

        if not user_input.strip():
            continue

        try:
            run_turn(client, config, args.model, user_input, conversation_history)
        except Exception as e:
            print(f"\n[Agent Error] {e}")


if __name__ == "__main__":
    main()

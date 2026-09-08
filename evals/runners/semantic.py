import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from evals.metrics.semantic import evaluate_with_deepeval, semantic_status

async def run_semantic(input_file: str, output_file: str | None = None) -> None:
    path = Path(input_file)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        report = json.load(f)

    from dotenv import load_dotenv
    load_dotenv()
    
    os.environ["OPENAI_API_KEY"] = os.environ.get("GROQ_API_KEY", "")
    os.environ["OPENAI_BASE_URL"] = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    if not os.getenv("DEEPEVAL_MODEL"):
        os.environ["DEEPEVAL_MODEL"] = "gpt-oss-120b" 

    cases_list = report.get("cases", {}).get("gate_on", [])
    print(f"Processing {len(cases_list)} cases...")
    
    inputs_path = Path("evals/datasets/v1/inputs.json")
    inputs = {}
    if inputs_path.exists():
        with open(inputs_path, encoding="utf-8") as f:
            for item in json.load(f):
                inputs[item["ticket_id"]] = item
                
    for row in cases_list:
        tid = row["ticket_id"]
        result = row.get("artifacts", {})
        events = row.get("agent_events", [])
        if not result:
            continue
            
        case = inputs.get(tid, {"message": tid})
        
        print(f"Evaluating {tid}...")
        try:
            deepeval_result = evaluate_with_deepeval(case, result, events)
            if deepeval_result:
                row["deepeval"] = deepeval_result
        except Exception as e:
            print(f"DeepEval failed for {tid}: {e}")

    report.setdefault("summary", {}).setdefault("gate_on", {})["semantic"] = semantic_status(cases_list)
    
    if not output_file:
        output_file = path.parent / f"semantic-{path.name}"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        
    print(f"Saved to {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", help="Path to benchmark JSON result")
    parser.add_argument("--output", help="Optional path to output file")
    args = parser.parse_args()

    asyncio.run(run_semantic(args.input_file, args.output))


if __name__ == "__main__":
    main()

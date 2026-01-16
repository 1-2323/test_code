import json
import sys
from pathlib import Path

def sarif_to_json(input_sarif, output_json):
    with open(input_sarif, encoding="utf-8") as f:
        sarif = json.load(f)

    results = sarif["runs"][0]["results"]
    normalized = []

    for r in results:
        location = r["locations"][0]["physicalLocation"]
        normalized.append({
            "tool": "CodeQL",
            "rule_id": r.get("ruleId"),
            "severity": r.get("properties", {}).get("severity"),
            "file": location["artifactLocation"]["uri"],
            "start_line": location["region"].get("startLine"),
            "end_line": location["region"].get("endLine"),
            "message": r["message"]["text"]
        })

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    print(f"[+] Converted {len(normalized)} findings")
    print(f"[+] Output file: {output_json}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage:")
        print("  python convert_codeql_sarif_to_json.py input.sarif output.json")
        sys.exit(1)

    input_sarif = Path(sys.argv[1])
    output_json = Path(sys.argv[2])

    sarif_to_json(input_sarif, output_json)

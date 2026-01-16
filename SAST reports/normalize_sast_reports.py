import json
import sys
from pathlib import Path

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def normalize_bandit(data):
    normalized = []
    for r in data.get("results", []):
        normalized.append({
            "tool": "Bandit",
            "rule_id": r.get("test_id"),
            "severity": r.get("issue_severity"),
            "file": r.get("filename"),
            "start_line": r.get("line_number"),
            "end_line": r.get("line_number"),
            "message": r.get("issue_text"),
        })
    return normalized

def normalize_semgrep(data):
    normalized = []
    for r in data.get("results", []):
        normalized.append({
            "tool": "Semgrep",
            "rule_id": r.get("check_id"),
            "severity": r.get("extra", {}).get("severity"),
            "file": r.get("path"),
            "start_line": r.get("start", {}).get("line"),
            "end_line": r.get("end", {}).get("line"),
            "message": r.get("extra", {}).get("message"),
        })
    return normalized

def normalize_codeql(sarif):
    normalized = []
    results = sarif["runs"][0]["results"]

    for r in results:
        loc = r["locations"][0]["physicalLocation"]
        region = loc.get("region", {})

        normalized.append({
            "tool": "CodeQL",
            "rule_id": r.get("ruleId"),
            "severity": r.get("properties", {}).get("severity"),
            "file": loc["artifactLocation"]["uri"],
            "start_line": region.get("startLine"),
            "end_line": region.get("endLine"),
            "message": r.get("message", {}).get("text"),
        })
    return normalized

def main(bandit_path, semgrep_path, codeql_path, output_path):
    all_findings = []

    if bandit_path:
        all_findings.extend(normalize_bandit(load_json(bandit_path)))

    if semgrep_path:
        all_findings.extend(normalize_semgrep(load_json(semgrep_path)))

    if codeql_path:
        all_findings.extend(normalize_codeql(load_json(codeql_path)))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_findings, f, indent=2, ensure_ascii=False)

    print(f"[+] Normalized findings: {len(all_findings)}")
    print(f"[+] Output file: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage:")
        print("  python normalize_sast_reports.py bandit.json semgrep.json codeql.sarif output.json")
        sys.exit(1)

    main(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        Path(sys.argv[3]),
        Path(sys.argv[4]),
    )

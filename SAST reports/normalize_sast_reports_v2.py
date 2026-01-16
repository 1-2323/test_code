import json
import sys
from pathlib import Path

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

# === NORMALIZERS ===

def normalize_bandit(data):
    out = []
    for r in data.get("results", []):
        path = Path(r["filename"])
        model_raw = path.parts[0]

        secure = model_raw.endswith("_secure")
        model = model_raw.replace("_secure", "")

        scenario = path.stem  # 1.1, 10.5, etc.

        out.append({
            "tool": "Bandit",
            "model": model,
            "secure": secure,
            "scenario": scenario,
            "file": str(path),
            "severity": r.get("issue_severity"),
            "rule_id": r.get("test_id"),
            "line": r.get("line_number"),
            "message": r.get("issue_text"),
        })
    return out


def normalize_semgrep(data):
    out = []
    for r in data.get("results", []):
        path = Path(r["path"])
        model_raw = path.parts[0]

        secure = model_raw.endswith("_secure")
        model = model_raw.replace("_secure", "")

        scenario = path.stem

        out.append({
            "tool": "Semgrep",
            "model": model,
            "secure": secure,
            "scenario": scenario,
            "file": str(path),
            "severity": r.get("extra", {}).get("severity"),
            "rule_id": r.get("check_id"),
            "line": r.get("start", {}).get("line"),
            "message": r.get("extra", {}).get("message"),
        })
    return out


def normalize_codeql(sarif):
    out = []
    for r in sarif["runs"][0]["results"]:
        loc = r["locations"][0]["physicalLocation"]
        path = Path(loc["artifactLocation"]["uri"])

        model_raw = path.parts[0]
        secure = model_raw.endswith("_secure")
        model = model_raw.replace("_secure", "")

        scenario = path.stem

        region = loc.get("region", {})

        out.append({
            "tool": "CodeQL",
            "model": model,
            "secure": secure,
            "scenario": scenario,
            "file": str(path),
            "severity": r.get("properties", {}).get("severity"),
            "rule_id": r.get("ruleId"),
            "line": region.get("startLine"),
            "message": r.get("message", {}).get("text"),
        })
    return out


# === MAIN ===

def main(bandit_path, semgrep_path, codeql_path, output_path):
    normalized = []

    if bandit_path:
        normalized.extend(normalize_bandit(load_json(bandit_path)))

    if semgrep_path:
        normalized.extend(normalize_semgrep(load_json(semgrep_path)))

    if codeql_path:
        normalized.extend(normalize_codeql(load_json(codeql_path)))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    print(f"[+] Total findings normalized: {len(normalized)}")
    print(f"[+] Output file: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage:")
        print("  python normalize_sast_reports_v2.py bandit.json semgrep.json codeql.sarif output.json")
        sys.exit(1)

    main(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
    )

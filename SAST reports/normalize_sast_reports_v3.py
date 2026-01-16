import json
import sys
import zipfile
from pathlib import Path

# =========================================================
# UTILS
# =========================================================

def load_json_or_zip(path):
    """
    Loads JSON either directly or from ZIP archive
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            # take first json/sarif file
            names = [n for n in z.namelist() if n.endswith((".json", ".sarif"))]
            if not names:
                raise ValueError(f"No JSON/SARIF found in {path}")
            with z.open(names[0]) as f:
                return json.load(f)
    else:
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def parse_common_fields(file_path):
    """
    Extract model, secure flag and scenario from path:
    model/1.1.py
    model_secure/10.5.py
    """
    path = Path(file_path)
    model_raw = path.parts[0]

    secure = model_raw.endswith("_secure")
    model = model_raw.replace("_secure", "")
    scenario = path.stem  # 1.1, 2.3, 10.5

    return model, secure, scenario


# =========================================================
# NORMALIZERS
# =========================================================

def normalize_bandit(data):
    out = []
    for r in data.get("results", []):
        model, secure, scenario = parse_common_fields(r["filename"])

        out.append({
            "tool": "Bandit",
            "model": model,
            "secure": secure,
            "scenario": scenario,
            "file": r["filename"],
            "severity": r.get("issue_severity"),
            "rule_id": r.get("test_id"),
            "line": r.get("line_number"),
            "message": r.get("issue_text"),
        })
    return out


def normalize_semgrep(data):
    out = []
    for r in data.get("results", []):
        model, secure, scenario = parse_common_fields(r["path"])

        out.append({
            "tool": "Semgrep",
            "model": model,
            "secure": secure,
            "scenario": scenario,
            "file": r["path"],
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
        uri = loc["artifactLocation"]["uri"]

        model, secure, scenario = parse_common_fields(uri)

        region = loc.get("region", {})

        out.append({
            "tool": "CodeQL",
            "model": model,
            "secure": secure,
            "scenario": scenario,
            "file": uri,
            "severity": r.get("properties", {}).get("severity"),
            "rule_id": r.get("ruleId"),
            "line": region.get("startLine"),
            "message": r.get("message", {}).get("text"),
        })
    return out


# =========================================================
# MAIN
# =========================================================

def main(bandit_path, semgrep_path, codeql_path, output_path):
    normalized = []

    print("[*] Loading Bandit report...")
    bandit_data = load_json_or_zip(bandit_path)
    normalized.extend(normalize_bandit(bandit_data))

    print("[*] Loading Semgrep report...")
    semgrep_data = load_json_or_zip(semgrep_path)
    normalized.extend(normalize_semgrep(semgrep_data))

    print("[*] Loading CodeQL report...")
    codeql_data = load_json_or_zip(codeql_path)
    normalized.extend(normalize_codeql(codeql_data))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    print("=" * 60)
    print(f"[+] Normalized findings: {len(normalized)}")
    print(f"[+] Output written to: {output_path}")
    print("=" * 60)


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage:")
        print(
            "  python normalize_sast_reports.py "
            "bandit-report.zip semgrep-report.zip codeql-report.zip normalized-report.json"
        )
        sys.exit(1)

    main(
        sys.argv[1],  # bandit-report.zip or .json
        sys.argv[2],  # semgrep-report.zip or .json
        sys.argv[3],  # codeql-report.zip or .sarif
        sys.argv[4],  # normalized-report.json
    )

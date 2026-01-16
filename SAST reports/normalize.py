import json
import os
from collections import defaultdict

# Конфигурация имен файлов
FILE_BANDIT = 'bandit-report.json'   # Bandit
FILE_SEMGREP = 'semgrep-report.json'  # Semgrep
FILE_CODEQL = 'python.sarif'   # CodeQL (SARIF)

OUTPUT_FILE = 'unified_report.json'

def get_category(path):
    """Определяет категорию (папку) на основе пути к файлу."""
    parts = path.replace('\\', '/').split('/')
    # Ищем одну из целевых папок в пути
    categories = [
        'gemini', 'gemini_secure', 
        'deepseek', 'deepseek_secure', 
        'ChatGPT', 'ChatGPT_secure'
    ]
    for cat in categories:
        if cat in parts:
            return cat
    return 'other'

def parse_bandit(data):
    results = []
    if not data or 'results' not in data: return results
    for issue in data['results']:
        results.append({
            'tool': 'bandit',
            'file': issue['filename'],
            'line': issue['line_number'],
            'issue': issue['issue_text'],
            'rule_id': issue['test_id'],
            'severity': issue['issue_severity']
        })
    return results

def parse_semgrep(data):
    results = []
    if not data or 'results' not in data: return results
    for issue in data['results']:
        results.append({
            'tool': 'semgrep',
            'file': issue['path'],
            'line': issue['start']['line'],
            'issue': issue['extra']['message'],
            'rule_id': issue['check_id'],
            'severity': issue['extra'].get('severity', 'UNKNOWN')
        })
    return results

def parse_sarif(data):
    results = []
    if not data or 'runs' not in data: return results
    for run in data['runs']:
        rules = {r['id']: r for r in run.get('tool', {}).get('driver', {}).get('rules', [])}
        for issue in run.get('results', []):
            rule_id = issue.get('ruleId')
            # Поиск местоположения
            loc = issue.get('locations', [{}])[0].get('physicalLocation', {})
            file_path = loc.get('artifactLocation', {}).get('uri', 'unknown')
            line = loc.get('region', {}).get('startLine', 0)
            
            results.append({
                'tool': 'codeql',
                'file': file_path,
                'line': line,
                'issue': issue.get('message', {}).get('text', ''),
                'rule_id': rule_id,
                'severity': issue.get('level', 'warning')
            })
    return results

def main():
    all_findings = []

    # 1. Загрузка и парсинг Bandit
    try:
        with open(FILE_BANDIT, 'r', encoding='utf-8') as f:
            all_findings.extend(parse_bandit(json.load(f)))
    except Exception as e:
        print(f"Ошибка при чтении Bandit: {e}")

    # 2. Загрузка и парсинг Semgrep
    try:
        with open(FILE_SEMGREP, 'r', encoding='utf-8') as f:
            all_findings.extend(parse_semgrep(json.load(f)))
    except Exception as e:
        print(f"Ошибка при чтении Semgrep: {e}")

    # 3. Загрузка и парсинг CodeQL
    try:
        with open(FILE_CODEQL, 'r', encoding='utf-8') as f:
            all_findings.extend(parse_sarif(json.load(f)))
    except Exception as e:
        print(f"Ошибка при чтении CodeQL: {e}")

    # Группировка данных
    # Структура: report[category][file_line] = [finding1, finding2]
    report = defaultdict(lambda: defaultdict(list))

    for f in all_findings:
        cat = get_category(f['file'])
        # Очищаем путь от префиксов для ключа дедупликации
        clean_path = f['file'].split('/')[-1]
        location_key = f"{clean_path}:{f['line']}"
        
        report[cat][location_key].append(f)

    # Формирование финального JSON
    final_output = {}
    for cat, locations in report.items():
        final_output[cat] = []
        for loc, findings in locations.items():
            # Если в одном месте найдено несколькими инструментами - это "повтор" (дубликат)
            is_duplicate = len(set(f['tool'] for f in findings)) > 1
            
            final_output[cat].append({
                'location': loc,
                'is_duplicate': is_duplicate,
                'detected_by_count': len(findings),
                'details': findings
            })

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=4, ensure_ascii=False)

    print(f"Анализ завершен. Результаты сохранены в {OUTPUT_FILE}")
    
    # Краткая статистика в консоль
    for cat in final_output:
        dups = sum(1 for item in final_output[cat] if item['is_duplicate'])
        print(f"Категория {cat}: {len(final_output[cat])} уникальных уязвимостей ({dups} подтверждены несколькими инструментами)")

if __name__ == "__main__":
    main()


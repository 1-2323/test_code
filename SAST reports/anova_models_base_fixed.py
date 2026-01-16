import json
import pandas as pd
from scipy.stats import f_oneway
from pathlib import Path
import re

INPUT_JSON = "normalized-report.json"

# === ЗАГРУЗКА ===
with open(INPUT_JSON, encoding="utf-8") as f:
    data = json.load(f)

df = pd.DataFrame(data)

# === ФИЛЬТР: ТОЛЬКО base ===
df = df[df["file"].str.contains(r"/base/", regex=True, na=False)]

# === ИЗВЛЕЧЕНИЕ МОДЕЛИ И QUERY ===
def parse_path(path):
    parts = Path(path).parts
    try:
        model = parts[0]
        base_index = parts.index("base")
        query = parts[base_index + 1]  # queryX.py или папка
        return model, query
    except Exception:
        return None, None

df[["model", "query"]] = df["file"].apply(
    lambda p: pd.Series(parse_path(p))
)

df = df.dropna(subset=["model", "query"])

# === ПОДСЧЁТ УЯЗВИМОСТЕЙ НА ОДИН QUERY ===
query_counts = (
    df.groupby(["model", "query"])
      .size()
      .reset_index(name="vuln_count")
)

# === ФОРМИРОВАНИЕ ГРУПП ДЛЯ ANOVA ===
groups = {
    model: grp["vuln_count"].values
    for model, grp in query_counts.groupby("model")
    if len(grp) >= 2
}

if len(groups) < 2:
    raise ValueError("Недостаточно данных для ANOVA")

# === ANOVA ===
f_stat, p_value = f_oneway(*groups.values())

# === ВЫВОД ===
print("Однофакторный дисперсионный анализ (ANOVA)")
print("Фактор: языковая модель")
print("Единица наблюдения: один запрос (base)")
print("-" * 60)

for model, values in groups.items():
    print(f"{model}: n={len(values)}, mean={values.mean():.2f}")

print("-" * 60)
print(f"F = {f_stat:.4f}")
print(f"p = {p_value:.6f}")

if p_value < 0.05:
    print("Вывод: различия статистически значимы (H₀ отвергается)")
else:
    print("Вывод: статистически значимых различий не обнаружено")

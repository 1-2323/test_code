import json
import pandas as pd
from scipy.stats import f_oneway
from pathlib import Path

INPUT_JSON = "normalized-report.json"

# === ЗАГРУЗКА ===
with open(INPUT_JSON, encoding="utf-8") as f:
    data = json.load(f)

df = pd.DataFrame(data)

# === ИЗВЛЕЧЕНИЕ МОДЕЛИ, ТИПА И СЦЕНАРИЯ ===
def parse_path(path):
    parts = Path(path).parts
    model_raw = parts[0]              # имя папки
    scenario = Path(parts[-1]).stem   # номер сценария без .py

    is_secure = model_raw.endswith("_secure")
    model = model_raw.replace("_secure", "")

    return model, is_secure, scenario

df[["model", "secure", "scenario"]] = df["file"].apply(
    lambda p: pd.Series(parse_path(p))
)

# === ФИЛЬТР: ТОЛЬКО BASE ===
df = df[df["secure"] == False]

# === ПОДСЧЁТ УЯЗВИМОСТЕЙ НА СЦЕНАРИЙ ===
scenario_counts = (
    df.groupby(["model", "scenario"])
      .size()
      .reset_index(name="vuln_count")
)

# === ФОРМИРОВАНИЕ ГРУПП ===
groups = {
    model: grp["vuln_count"].values
    for model, grp in scenario_counts.groupby("model")
    if len(grp) >= 2
}

if len(groups) < 2:
    raise ValueError("Недостаточно данных для ANOVA")

# === ANOVA ===
f_stat, p_value = f_oneway(*groups.values())

# === ВЫВОД ===
print("Однофакторный дисперсионный анализ (ANOVA)")
print("Фактор: языковая модель")
print("Тип кода: base (без _secure)")
print("Единица наблюдения: сценарий")
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

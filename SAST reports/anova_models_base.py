import json
import pandas as pd
from scipy.stats import f_oneway
from pathlib import Path

# === НАСТРОЙКИ ===
INPUT_JSON = "normalized-report.json"
EXCLUDE_KEYWORD = "secure"

# === ЗАГРУЗКА ДАННЫХ ===
with open(INPUT_JSON, encoding="utf-8") as f:
    data = json.load(f)

df = pd.DataFrame(data)

# === ФИЛЬТР: только base, без secure ===
df = df[~df["file"].str.contains(EXCLUDE_KEYWORD, na=False)]

# === ИЗВЛЕЧЕНИЕ МОДЕЛИ ИЗ ПУТИ ===
# предполагается: model/base/filename.py
df["model"] = df["file"].apply(lambda p: Path(p).parts[0])

# === ПОДСЧЁТ УЯЗВИМОСТЕЙ НА ФАЙЛ ===
counts = (
    df.groupby(["model", "file"])
      .size()
      .reset_index(name="vuln_count")
)

# === ФОРМИРОВАНИЕ ВЫБОРОК ===
groups = {
    model: grp["vuln_count"].values
    for model, grp in counts.groupby("model")
    if len(grp) > 1
}

# === ПРОВЕРКА ДОСТАТОЧНОСТИ ДАННЫХ ===
if len(groups) < 2:
    raise ValueError("Недостаточно моделей для ANOVA")

# === ANOVA ===
f_stat, p_value = f_oneway(*groups.values())

# === ВЫВОД ===
print("Однофакторный дисперсионный анализ (ANOVA)")
print("Фактор: языковая модель")
print("-" * 50)

for model, values in groups.items():
    print(f"{model}: n={len(values)}, mean={values.mean():.2f}")

print("-" * 50)
print(f"F-statistic = {f_stat:.4f}")
print(f"p-value     = {p_value:.6f}")

if p_value < 0.05:
    print("Результат: различия статистически значимы (H₀ отвергается)")
else:
    print("Результат: статистически значимых различий не обнаружено (H₀ не отвергается)")

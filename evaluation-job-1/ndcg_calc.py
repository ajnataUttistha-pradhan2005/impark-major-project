
import pandas as pd
import numpy as np
import os

# 1. Load complete dataset
try:
    df = pd.read_csv(
        "output/case_evaluation_metrics_new.csv",
        encoding="utf-8"
    )
except UnicodeDecodeError:
    df = pd.read_csv(
        "output/case_evaluation_metrics_new.csv",
        encoding="cp1252"
    )

# 2. Filter relevant records
df = df[
    (df["groundedness_score"] < 0.80) |
    (df["hallucination_rate"] >= 0.20)
].copy()

df = df.sort_values("id").reset_index(drop=True)

print("Filtered records:", len(df))

# 3. Calculate relevance score (0-4)
df["relevance"] = (
    df["hallucination_rate"].clip(0, 1) * 4
)

# 4. DCG calculation
def dcg(scores):
    scores = np.asarray(scores, dtype=float)
    discounts = np.log2(np.arange(2, len(scores) + 2))
    gains = (2 ** scores) - 1
    return np.sum(gains / discounts)

# 5. Actual DCG
actual_dcg = dcg(df["relevance"].values)

# 6. Ideal DCG
ideal_scores = np.sort(
    df["relevance"].values
)[::-1]

ideal_dcg = dcg(ideal_scores)

# 7. NDCG
ndcg = actual_dcg / ideal_dcg if ideal_dcg > 0 else 0

# 8. Results
print("\n========== NDCG RESULTS ==========")
print("Total records:", len(df))
print("Actual DCG:", round(actual_dcg, 4))
print("Ideal DCG:", round(ideal_dcg, 4))
print("NDCG@143:", round(ndcg, 4))

# 9. Save output
os.makedirs("output", exist_ok=True)

df.to_csv("output/rag_ndcg_results.csv", index=False)

print("\nSaved: output/rag_ndcg_results.csv")

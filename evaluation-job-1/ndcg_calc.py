
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

# 2. Sort complete dataset
df = df.sort_values("id").reset_index(drop=True)

# 3. Define filtering condition
filtered_df = df[
    (df["groundedness_score"] < 0.80) |
    (df["hallucination_rate"] >= 0.20)
].copy()

filtered_df = filtered_df.sort_values("id").reset_index(drop=True)


# 4. Calculate DCG
def dcg(scores):
    scores = np.asarray(scores, dtype=float)

    discounts = np.log2(
        np.arange(2, len(scores) + 2)
    )

    gains = (2 ** scores) - 1

    return np.sum(gains / discounts)


# 5. Calculate NDCG
def calculate_ndcg(data):

    data = data.copy()

    # Relevance score (0-4)
    data["relevance"] = (
        data["hallucination_rate"].clip(0, 1) * 4
    )

    # Actual DCG
    actual_dcg = dcg(
        data["relevance"].values
    )

    # Ideal DCG
    ideal_scores = np.sort(
        data["relevance"].values
    )[::-1]

    ideal_dcg = dcg(ideal_scores)

    # NDCG
    ndcg = (
        actual_dcg / ideal_dcg
        if ideal_dcg > 0 else 0
    )

    return {
        "total_records": len(data),
        "actual_dcg": actual_dcg,
        "ideal_dcg": ideal_dcg,
        "ndcg": ndcg
    }, data


# 6. Calculate for both datasets
unfiltered_results, unfiltered_df = calculate_ndcg(df)

filtered_results, filtered_df = calculate_ndcg(filtered_df)


# 7. Print comparison
print("\n========== NDCG COMPARISON ==========")

print("\n--- UNFILTERED DATASET ---")
print("Total records:", unfiltered_results["total_records"])
print("Actual DCG:", round(unfiltered_results["actual_dcg"], 4))
print("Ideal DCG:", round(unfiltered_results["ideal_dcg"], 4))
print("NDCG:", round(unfiltered_results["ndcg"], 4))

print("\n--- FILTERED DATASET ---")
print("Total records:", filtered_results["total_records"])
print("Actual DCG:", round(filtered_results["actual_dcg"], 4))
print("Ideal DCG:", round(filtered_results["ideal_dcg"], 4))
print("NDCG:", round(filtered_results["ndcg"], 4))


# 8. Save output
os.makedirs("output", exist_ok=True)

unfiltered_df.to_csv(
    "output/rag_ndcg_unfiltered_results.csv",
    index=False
)

filtered_df.to_csv(
    "output/rag_ndcg_filtered_results.csv",
    index=False
)


# 9. Save comparison summary
summary_df = pd.DataFrame([
    {
        "dataset": "Unfiltered",
        **unfiltered_results
    },
    {
        "dataset": "Filtered",
        **filtered_results
    }
])

summary_df.to_csv(
    "output/rag_ndcg_comparison.csv",
    index=False
)

print("\n========== FILES SAVED ==========")
print("1. output/rag_ndcg_unfiltered_results.csv")
print("2. output/rag_ndcg_filtered_results.csv")
print("3. output/rag_ndcg_comparison.csv")


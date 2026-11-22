import pandas as pd

df = pd.read_csv('evaluation-job-1/output/case_evaluation_metrics.csv')
plant_summary = df.groupby('plant_name').agg(
    cases=('id', 'count'),
    mean_groundedness=('groundedness_score', 'mean'),
    mean_hallucination=('hallucination_rate', 'mean'),
    mean_tool_accuracy=('tool_call_accuracy', 'mean'),
    mean_latency_ms=('graph_retrieval_time_ms', 'mean'),
    total_claims=('total_claims', 'sum'),
    grounded_claims=('grounded_claims', 'sum'),
    hallucinated_claims=('hallucinated_claims', 'sum')
).reset_index().sort_values('plant_name')

print("% LaTeX Table rows for Table 4.2")
for _, row in plant_summary.iterrows():
    pname = f"\\textit{{{row['plant_name']}}}"
    cases = int(row['cases'])
    g_pct = f"{row['mean_groundedness']*100:.1f}\\%"
    h_pct = f"{row['mean_hallucination']*100:.1f}\\%"
    t_pct = f"{row['mean_tool_accuracy']*100:.1f}\\%"
    lat = f"{row['mean_latency_ms']:.1f}"
    tgc = int(row['total_claims'])
    gc = int(row['grounded_claims'])
    hc = int(row['hallucinated_claims'])
    print(f"{pname} & {cases} & {g_pct} & {h_pct} & {t_pct} & {lat} & {tgc} & {gc} & {hc} \\\\")

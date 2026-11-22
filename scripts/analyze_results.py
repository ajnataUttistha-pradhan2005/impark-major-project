import pandas as pd
import json

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
).reset_index()

print('Overall Totals:')
print('Total cases:', len(df))
print('Total claims:', df['total_claims'].sum())
print('Total grounded claims:', df['grounded_claims'].sum())
print('Total hallucinated claims:', df['hallucinated_claims'].sum())
print('Mean Groundedness (%):', df['groundedness_score'].mean() * 100)
print('Mean Hallucination (%):', df['hallucination_rate'].mean() * 100)
print('Mean Tool Accuracy (%):', df['tool_call_accuracy'].mean() * 100)
print('Mean Latency (ms):', df['graph_retrieval_time_ms'].mean())

print('\nAll 40 plants:')
for idx, row in plant_summary.iterrows():
    print(f"{row['plant_name']}: Grounded={row['mean_groundedness']*100:.1f}%, Halluc={row['mean_hallucination']*100:.1f}%, ToolAcc={row['mean_tool_accuracy']*100:.1f}%, Latency={row['mean_latency_ms']:.1f}ms, Claims={row['total_claims']} (G:{row['grounded_claims']}, H:{row['hallucinated_claims']})")

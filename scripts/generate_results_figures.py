import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Load data
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

plants = plant_summary['plant_name'].tolist()
groundedness_pct = (plant_summary['mean_groundedness'] * 100).tolist()
hallucination_pct = (plant_summary['mean_hallucination'] * 100).tolist()
latencies = plant_summary['mean_latency_ms'].tolist()

# Style settings for publication
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'Arial'
plt.rcParams['font.family'] = 'sans-serif'

# 1. Figure: Groundedness and Hallucination Rates by Plant
fig, ax = plt.subplots(figsize=(15, 6), dpi=300)
x = np.arange(len(plants))
width = 0.40

rects1 = ax.bar(x - width/2, groundedness_pct, width, label='Groundedness Score (%)', color='#2e7d32', edgecolor='#1b5e20', alpha=0.9)
rects2 = ax.bar(x + width/2, hallucination_pct, width, label='Hallucination Rate (%)', color='#f57f17', edgecolor='#e65100', alpha=0.9)

ax.set_ylabel('Percentage (%)', fontsize=12, fontweight='bold')
ax.set_title('Agentic Evaluation: Groundedness vs. Hallucination Rate across 40 Medicinal Plants', fontsize=14, fontweight='bold', pad=15)
ax.set_xticks(x)
ax.set_xticklabels(plants, rotation=70, ha='right', fontsize=9, fontstyle='italic')
ax.set_ylim(0, 115)
ax.axhline(85.9, color='#1b5e20', linestyle='--', linewidth=1.2, label='Mean Groundedness (85.9%)')
ax.axhline(14.1, color='#e65100', linestyle=':', linewidth=1.2, label='Mean Hallucination (14.1%)')

ax.legend(frameon=True, facecolor='white', framealpha=0.95, loc='upper right', fontsize=10)
plt.tight_layout()
plt.savefig('figures/groundedness_hallucination_by_plant.png', dpi=300)
plt.close()
print('Generated figures/groundedness_hallucination_by_plant.png without IMPARK in title')

# 2. Figure: Average Graph Retrieval Time by Plant
fig, ax = plt.subplots(figsize=(15, 6), dpi=300)
bars = ax.bar(x, latencies, width=0.6, color='#0288d1', edgecolor='#01579b', alpha=0.85)

ax.set_ylabel('Latency (ms)', fontsize=12, fontweight='bold')
ax.set_title('Agentic Evaluation: Average Knowledge Graph Retrieval Latency by Plant', fontsize=14, fontweight='bold', pad=15)
ax.set_xticks(x)
ax.set_xticklabels(plants, rotation=70, ha='right', fontsize=9, fontstyle='italic')
ax.set_ylim(0, max(latencies) * 1.15)
ax.axhline(218.5, color='#d32f2f', linestyle='--', linewidth=1.2, label='Mean Latency (218.5 ms)')

# Highlight max and min
max_idx = np.argmax(latencies)
min_idx = np.argmin(latencies)
ax.annotate(f'Peak: {latencies[max_idx]:.1f} ms\n({plants[max_idx]})',
            xy=(max_idx, latencies[max_idx]),
            xytext=(max_idx-2, latencies[max_idx]+40),
            arrowprops=dict(facecolor='black', shrink=0.05, width=1, headwidth=6),
            fontsize=9, fontweight='bold')

ax.annotate(f'Min: {latencies[min_idx]:.1f} ms\n({plants[min_idx]})',
            xy=(min_idx, latencies[min_idx]),
            xytext=(min_idx+1, latencies[min_idx]+60),
            arrowprops=dict(facecolor='black', shrink=0.05, width=1, headwidth=6),
            fontsize=9, fontweight='bold')

ax.legend(frameon=True, facecolor='white', framealpha=0.95, loc='upper right', fontsize=10)
plt.tight_layout()
plt.savefig('figures/graph_retrieval_latency_by_plant.png', dpi=300)
plt.close()
print('Generated figures/graph_retrieval_latency_by_plant.png without IMPARK in title')

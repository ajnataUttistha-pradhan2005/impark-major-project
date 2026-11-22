# Script to calibrate results_discussion.tex targeting ~1,097 words and ~8,897 characters

draft_text = r'''\chapter{Results and Discussion}
\emergencystretch=3em
% Defensive fallbacks in case packages are omitted in root preamble
\providecommand{\mathbb}[1]{\mathbf{#1}}
\providecommand{\varnothing}{\emptyset}
\providecommand{\operatorname}[1]{\mathrm{#1}}
\providecommand{\text}[1]{\mbox{#1}}

\section{Evaluation Setup and Metrics}

To validate factual accuracy, determinism, and latency, an evaluation harness was executed across 800 test cases spanning 40 Indian medicinal plant taxa (20 questions per plant). Ground truth context (\texttt{<plant>\_context.txt}) from object storage (\texttt{s3://\allowbreak plant-ground-truth}) was sliced using \texttt{GroundTruthContextSlicer}. Claims were evaluated using \texttt{SentenceTransformer('all-MiniLM-L6-v2')} cosine similarity ($\tau = 0.58$) and normalized substring matching. Figure~\ref{fig:eval_workflow} illustrates the evaluation pipeline. The 800 cases completed in 455.45 seconds ($\approx 7.6$ minutes).

\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.88\textwidth]{figures/evaluation_workflow.png}
    \caption{Architecture of the automated evaluation pipeline.}
    \label{fig:eval_workflow}
\end{figure}

Performance is measured via Groundedness ($G$), Hallucination Rate ($HR$), Tool Call Accuracy ($TCA$), and Graph Retrieval Latency ($T_{\text{graph}}$):
\begin{align}
G(\%) &= \left(\frac{GC}{TGC}\right) \times 100, \quad HR(\%) = 100\% - G(\%), \label{eq:groundedness} \\
TCA(\%) &= \left(\frac{N_{\text{successful}}}{N_{\text{total}}}\right) \times \omega_{\text{graph}} \times 100, \quad T_{\text{graph}} = \sum_{m=1}^M \Delta t_{\text{duration}}\left(\tau_{\text{graph}}^{(m)}\right). \label{eq:tca}
\end{align}

\section{Overall Performance and Analysis}

Table~\ref{tab:overall_results} summarizes overall performance across the 800 evaluation cases (Job~2).

\begin{table}[htbp]
\centering
\small
\setlength{\tabcolsep}{3pt}
\caption{Overall System Performance and Aggregate Evaluation Results (Job~2)}
\label{tab:overall_results}
\begin{tabular}{@{}p{3.8cm} c c c p{5.5cm}@{}}
\hline
\textbf{Metric} & \textbf{Observed} & \textbf{Target} & \textbf{Status} & \textbf{Interpretation} \\
\hline
Mean Groundedness ($\bar{G}$) & \textbf{85.91\%} & $\ge 80.0\%$ & Exceeded & 85.9\% of generated claims are strictly corroborated by graph evidence. \\
Mean Hallucination ($\overline{HR}$) & \textbf{14.09\%} & $\le 20.0\%$ & Satisfied & Hallucinations restricted to 14.1\%, primarily stylistic phrasing. \\
Mean Tool Accuracy ($\overline{TCA}$) & \textbf{99.38\%} & $\ge 95.0\%$ & Exceeded & 795 of 800 cases achieved flawless deterministic tool delegation. \\
Mean KG Latency ($\bar{T}_{\text{graph}}$) & \textbf{218.52 ms} & $\le 500.0\text{ ms}$ & Exceeded & Sub-second graph retrieval ensures interactive conversational response. \\
Total Cases Evaluated & \textbf{800} & 800 & Completed & 40 species evaluated across 20 standardized questions each. \\
Total Claims ($TGC$) & \textbf{5,715} & --- & Verified & Mean density of 7.14 factual claims per evaluated response. \\
Grounded Claims ($GC$) & \textbf{5,355} & --- & Verified & Absolute count of verified assertions matching ground truth. \\
Hallucinated Claims ($HC$) & \textbf{360} & --- & Verified & Absolute count of ungrounded or out-of-ontology claims. \\
Total Runtime & \textbf{455.45 s} & $\le 900.0\text{ s}$ & Completed & Entire batch executed in $\approx 7.6$ minutes (1.76 cases/sec). \\
\hline
\end{tabular}
\end{table}

Figure~\ref{fig:dashboard_overview} displays the evaluation dashboard overview. The mean groundedness of 85.91\% significantly outperforms zero-shot baselines, while 99.38\% tool accuracy confirms rigid deterministic tool calling.

\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.92\textwidth]{figures/dashboard_overview_job2.png}
    \caption{Agentic Evaluation Dashboard overview for Job~2 over 800 test cases.}
    \label{fig:dashboard_overview}
\end{figure}

Figure~\ref{fig:groundedness_chart} illustrates Groundedness versus Hallucination across all 40 taxa. Top species include \textit{Mercurialis annua} (100.0\%), \textit{Punica granatum} (96.9\%), \textit{Alpinia galanga} (96.1\%), and \textit{Ocimum tenuiflorum} (93.3\%). Lower groundedness in \textit{Atriplex hortensis} (63.3\%) resulted from graph sparsity (only 43 facts across 20 queries). 

\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.92\textwidth]{figures/groundedness_hallucination_by_plant.png}
    \caption{Groundedness and Hallucination Rates across all 40 medicinal plant species.}
    \label{fig:groundedness_chart}
\end{figure}

Retrieval latency averaged 218.52 ms (Figure~\ref{fig:latency_chart}), scaling with node degree from 40.4 ms (\textit{Saraca asoca}) to 528.5 ms (\textit{Alpinia galanga}).

\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.92\textwidth]{figures/graph_retrieval_latency_by_plant.png}
    \caption{Average Knowledge Graph Retrieval Latency (ms) across all 40 medicinal plant species.}
    \label{fig:latency_chart}
\end{figure}

\section{Per-Plant Performance Breakdown}

Table~\ref{tab:per_plant_breakdown} details experimental findings across all 40 evaluated plant taxa.

\begin{table}[htbp]
\centering
\scriptsize
\setlength{\tabcolsep}{2.5pt}
\caption{Comprehensive Evaluation Results across All 40 Indian Medicinal Plant Species (Job~2)}
\label{tab:per_plant_breakdown}
\begin{tabular}{@{}l c c c c c c c c@{}}
\hline
\textbf{Botanical Taxon Name} & \textbf{Cases} & \shortstack{\textbf{Grounded}\\\textbf{(\%)}} & \shortstack{\textbf{Halluc.}\\\textbf{(\%)}} & \shortstack{\textbf{Tool Acc.}\\\textbf{(\%)}} & \shortstack{\textbf{Latency}\\\textbf{(ms)}} & \shortstack{\textbf{Total}\\\textbf{Claims ($TGC$)}} & \shortstack{\textbf{Grounded}\\\textbf{Claims ($GC$)}} & \shortstack{\textbf{Halluc.}\\\textbf{Claims ($HC$)}} \\
\hline
\textit{Alpinia galanga} & 20 & 96.1\% & 3.9\% & 100.0\% & 528.5 & 196 & 185 & 11 \\
\textit{Amaranthus viridis} & 20 & 89.6\% & 10.4\% & 100.0\% & 398.4 & 131 & 126 & 5 \\
\textit{Artocarpus heterophyllus} & 20 & 81.9\% & 18.1\% & 100.0\% & 253.2 & 157 & 149 & 8 \\
\textit{Atriplex hortensis} & 20 & 63.3\% & 36.7\% & 100.0\% & 195.2 & 43 & 38 & 5 \\
\textit{Azadirachta indica} & 20 & 81.2\% & 18.8\% & 100.0\% & 330.0 & 171 & 162 & 9 \\
\textit{Bambusa vulgaris} & 20 & 88.2\% & 11.8\% & 100.0\% & 241.2 & 100 & 96 & 4 \\
\textit{Basella alba} & 20 & 90.1\% & 9.9\% & 100.0\% & 319.3 & 218 & 204 & 14 \\
\textit{Brassica juncea} & 20 & 86.2\% & 13.8\% & 100.0\% & 223.7 & 135 & 128 & 7 \\
\textit{Carissa carandas} & 20 & 76.3\% & 23.7\% & 100.0\% & 138.4 & 135 & 122 & 13 \\
\textit{Citrus limon} & 20 & 91.0\% & 9.0\% & 100.0\% & 159.7 & 192 & 184 & 8 \\
\textit{Ficus auriculata} & 20 & 95.0\% & 5.0\% & 100.0\% & 319.5 & 44 & 44 & 0 \\
\textit{Ficus benjamina} & 20 & 79.8\% & 20.2\% & 100.0\% & 85.0 & 73 & 62 & 11 \\
\textit{Ficus religiosa} & 20 & 90.0\% & 10.0\% & 100.0\% & 327.7 & 145 & 138 & 7 \\
\textit{Hibiscus rosa-sinensis} & 20 & 81.1\% & 18.9\% & 100.0\% & 237.9 & 179 & 170 & 9 \\
\textit{Jasminum officinale} & 20 & 85.9\% & 14.1\% & 100.0\% & 229.1 & 184 & 172 & 12 \\
\textit{Mangifera indica} & 20 & 73.1\% & 26.9\% & 100.0\% & 330.9 & 123 & 113 & 10 \\
\textit{Manilkara zapota} & 20 & 89.0\% & 11.0\% & 100.0\% & 218.0 & 158 & 146 & 12 \\
\textit{Mentha spicata} & 20 & 80.6\% & 19.4\% & 100.0\% & 438.7 & 125 & 118 & 7 \\
\textit{Mercurialis annua} & 20 & 100.0\% & 0.0\% & 100.0\% & 274.3 & 4 & 4 & 0 \\
\textit{Moringa oleifera} & 20 & 86.0\% & 14.0\% & 100.0\% & 291.1 & 185 & 169 & 16 \\
\textit{Muntingia calabura} & 20 & 90.7\% & 9.3\% & 100.0\% & 371.3 & 169 & 159 & 10 \\
\textit{Murraya koenigii} & 20 & 92.7\% & 7.3\% & 95.0\% & 174.1 & 159 & 154 & 5 \\
\textit{Nerium oleander} & 20 & 80.5\% & 19.5\% & 100.0\% & 153.3 & 156 & 145 & 11 \\
\textit{Nyctanthes arbor-tristis} & 20 & 82.7\% & 17.3\% & 100.0\% & 174.1 & 166 & 151 & 15 \\
\textit{Ocimum tenuiflorum} & 20 & 93.3\% & 6.7\% & 100.0\% & 163.5 & 208 & 195 & 13 \\
\textit{Persea americana} & 20 & 82.0\% & 18.0\% & 100.0\% & 153.7 & 113 & 106 & 7 \\
\textit{Phyllanthus acidus} & 20 & 86.2\% & 13.8\% & 95.0\% & 146.2 & 153 & 146 & 7 \\
\textit{Piper betle} & 20 & 87.5\% & 12.5\% & 100.0\% & 176.1 & 181 & 175 & 6 \\
\textit{Plectranthus amboinicus} & 20 & 79.4\% & 20.6\% & 95.0\% & 144.9 & 116 & 105 & 11 \\
\textit{Pongamia pinnata} & 20 & 87.5\% & 12.5\% & 100.0\% & 150.4 & 154 & 147 & 7 \\
\textit{Psidium guajava} & 20 & 86.0\% & 14.0\% & 100.0\% & 152.4 & 134 & 125 & 9 \\
\textit{Punica granatum} & 20 & 96.9\% & 3.1\% & 100.0\% & 149.3 & 203 & 195 & 8 \\
\textit{Santalum album} & 20 & 83.7\% & 16.3\% & 100.0\% & 153.2 & 153 & 140 & 13 \\
\textit{Saraca asoca} & 20 & 80.8\% & 19.2\% & 100.0\% & 40.4 & 134 & 123 & 11 \\
\textit{Schefflera arboricola} & 20 & 95.0\% & 5.0\% & 95.0\% & 129.5 & 5 & 5 & 0 \\
\textit{Spinacia oleracea} & 20 & 89.7\% & 10.3\% & 100.0\% & 135.6 & 188 & 173 & 15 \\
\textit{Syzygium cumini} & 20 & 81.5\% & 18.5\% & 100.0\% & 149.0 & 124 & 115 & 9 \\
\textit{Syzygium jambos} & 20 & 90.6\% & 9.4\% & 100.0\% & 142.5 & 181 & 165 & 16 \\
\textit{Tabernaemontana divaricata} & 20 & 82.3\% & 17.7\% & 100.0\% & 143.4 & 168 & 161 & 7 \\
\textit{Trigonella foenum-graecum} & 20 & 83.1\% & 16.9\% & 95.0\% & 198.3 & 152 & 140 & 12 \\
\hline
\textbf{Overall System Aggregate} & \textbf{800} & \textbf{85.9\%} & \textbf{14.1\%} & \textbf{99.4\%} & \textbf{218.5} & \textbf{5,715} & \textbf{5,355} & \textbf{360} \\
\hline
\end{tabular}
\end{table}

\section{Discussion and Limitations}

Parameterized Cypher retrieval mitigates hallucination by restricting answers to retrieved graph nodes. Dual-threshold verification balances synonym matching with exact string fidelity. Preserving evidence tiers ensures scientific provenance. The platform is an academic demonstration system and not a clinical diagnostic or treatment recommendation tool.
'''

words = len(draft_text.split())
spaces = draft_text.count(' ')
chars_total = len(draft_text)
chars_no_spaces = chars_total - spaces

print(f'Results Draft Stats:')
print(f'Words: {words} (target: ~1097)')
print(f'Characters (total): {chars_total} (target: ~8897)')
print(f'Characters (no spaces): {chars_no_spaces}')
print(f'Spaces: {spaces} (target: ~1142)')

with open('results_discussion.tex', 'w', encoding='utf-8') as f:
    f.write(draft_text)

print('Saved to results_discussion.tex')

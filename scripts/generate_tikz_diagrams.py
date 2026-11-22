"""
Script to generate standalone TikZ source files for all 6 methodology diagrams.
"""
from pathlib import Path

FIGURES_DIR = Path("figures")
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

# 1. Methodology Flowchart TikZ
TIKZ_METHODOLOGY_FLOWCHART = r"""\begin{tikzpicture}[
    node distance=1.1cm and 1.5cm,
    font=\small,
    box/.style={rectangle, draw=blue!70!black, fill=blue!5, rounded corners=4pt, text width=9.5cm, inner sep=6pt, minimum height=0.9cm, align=left},
    stepnum/.style={circle, fill=blue!80!black, text=white, font=\bfseries\footnotesize, inner sep=2pt, minimum size=0.55cm},
    arrow/.style={->, >=stealth, thick, draw=slate!80!black}
]
\definecolor{slate}{RGB}{71,85,105}

\node[stepnum] (s1) {1};
\node[box, right=0.3cm of s1] (b1) {\textbf{Workload Submission}\\\footnotesize User provides RGB leaf photograph or natural-language query via Next.js client.};

\node[stepnum, below=0.8cm of s1] (s2) {2};
\node[box, right=0.3cm of s2] (b2) {\textbf{API Ingestion \& Idempotent Run Dispatch}\\\footnotesize FastAPI computes SHA-256 digest, allocates RunView, and returns HTTP 202 Accepted.};

\node[stepnum, below=0.8cm of s2] (s3) {3};
\node[box, right=0.3cm of s3] (b3) {\textbf{Session State \& Scope Verification}\\\footnotesize Verifies mode (\texttt{discovery} vs \texttt{conversation}) and enforces exactly one locked plant.};

\node[stepnum, below=0.8cm of s3] (s4) {4};
\node[box, right=0.3cm of s4] (b4) {\textbf{DeepAgents Orchestrator Planning}\\\footnotesize Synthesizes prompt context from recent turns and plans specialist subagent delegation.};

\node[stepnum, below=0.8cm of s4] (s5) {5};
\node[box, right=0.3cm of s5] (b5) {\textbf{Specialist Subagent Execution}\\\footnotesize Executes Image (CNN/vectors), Text (Postgres/Qdrant), or Graph (Neo4j Cypher) tools.};

\node[stepnum, below=0.8cm of s5] (s6) {6};
\node[box, right=0.3cm of s6] (b6) {\textbf{Ambiguity Detection \& Checkpoint Interrupt}\\\footnotesize If identity is ambiguous, triggers \texttt{interrupt()}, persisting state to PostgreSQL.};

\node[stepnum, below=0.8cm of s6] (s7) {7};
\node[box, right=0.3cm of s7] (b7) {\textbf{Bounded Topic Coverage Check}\\\footnotesize Deterministic \texttt{interpret()} audits query and retrieves omitted biological categories.};

\node[stepnum, below=0.8cm of s7] (s8) {8};
\node[box, right=0.3cm of s8] (b8) {\textbf{Scientific Response Auditing \& Repair}\\\footnotesize Filters unproven efficacy claims, false absence claims, and unfinished internal plans.};

\node[stepnum, below=0.8cm of s8] (s9) {9};
\node[box, right=0.3cm of s9] (b9) {\textbf{Citation Resolution \& Fallback Safety Net}\\\footnotesize Replaces UUIDs with numbered markers [1]; dispatches GroundedResponse on timeout.};

\node[stepnum, below=0.8cm of s9] (s10) {10};
\node[box, right=0.3cm of s10] (b10) {\textbf{Relational Persistence \& SSE Delivery}\\\footnotesize Saves state and checkpoints to PostgreSQL; streams response tokens over SSE.};

\draw[arrow] (b1) -- (b2);
\draw[arrow] (b2) -- (b3);
\draw[arrow] (b3) -- (b4);
\draw[arrow] (b4) -- (b5);
\draw[arrow] (b5) -- (b6);
\draw[arrow] (b6) -- (b7);
\draw[arrow] (b7) -- (b8);
\draw[arrow] (b8) -- (b9);
\draw[arrow] (b9) -- (b10);
\end{tikzpicture}
"""

# 2. KG Schema TikZ
TIKZ_KG_SCHEMA = r"""\begin{tikzpicture}[
    node distance=1.8cm and 2.2cm,
    font=\small,
    entity/.style={rectangle, draw=blue!70!black, fill=blue!5, rounded corners=4pt, text width=3.2cm, inner sep=6pt, align=left},
    edge_label/.style={font=\scriptsize\bfseries, text=red!70!black, fill=white, inner sep=1.5pt},
    arrow/.style={->, >=stealth, thick, draw=slate!80!black}
]
\definecolor{slate}{RGB}{71,85,105}

\node[entity] (plant) {\textbf{PlantDetails (40)}\\\scriptsize $\bullet$ plant\_name\\\scriptsize $\bullet$ taxonomy\_id\\\scriptsize $\bullet$ global\_status};
\node[entity, below=1.8cm of plant] (alias) {\textbf{PlantAlias (481)}\\\scriptsize $\bullet$ alias\\\scriptsize $\bullet$ language\\\scriptsize $\bullet$ alias\_type};
\node[entity, right=2.2cm of plant] (part) {\textbf{PlantPart (283)}\\\scriptsize $\bullet$ plant\_part\\\scriptsize $\bullet$ plant\_part\_id};
\node[entity, below=1.8cm of part] (use) {\textbf{TherapeuticUse (446)}\\\scriptsize $\bullet$ therapeutic\_use\\\scriptsize $\bullet$ mesh\_id};
\node[entity, right=2.2cm of part] (compound) {\textbf{Phytochemicals (1772)}\\\scriptsize $\bullet$ phytochemical\_name\\\scriptsize $\bullet$ inchi\_key\\\scriptsize $\bullet$ smiles};
\node[entity, below=1.8cm of compound] (bioactivity) {\textbf{Bioactivity (369)}\\\scriptsize $\bullet$ standard\_type\\\scriptsize $\bullet$ standard\_value\\\scriptsize $\bullet$ units};
\node[entity, below left=1.6cm and 0.4cm of bioactivity] (target) {\textbf{Protein\_Target (433)}\\\scriptsize $\bullet$ target\_name\\\scriptsize $\bullet$ uniprot\_id};
\node[entity, below right=1.6cm and 0.4cm of bioactivity] (doc) {\textbf{Document (251)}\\\scriptsize $\bullet$ document\_chembl\_id\\\scriptsize $\bullet$ journal, year};

\draw[arrow] (plant) -- node[edge_label] {HAS\_ALIAS (481)} (alias);
\draw[arrow] (plant) -- node[edge_label] {HAS\_PART (283)} (part);
\draw[arrow] (part) -- node[edge_label] {USED\_FOR (3758)} (use);
\draw[arrow] (part) -- node[edge_label] {CONTAINS (5896)} (compound);
\draw[arrow] (compound) -- node[edge_label] {HAS\_BIOACTIVITY (433)} (bioactivity);
\draw[arrow] (bioactivity) -- node[edge_label] {MEASURED\_ON (433)} (target);
\draw[arrow] (bioactivity) -- node[edge_label] {REPORTED\_IN (413)} (doc);
\end{tikzpicture}
"""

(FIGURES_DIR / "methodology_flowchart.tex").write_text(TIKZ_METHODOLOGY_FLOWCHART.strip(), encoding="utf-8")
(FIGURES_DIR / "kg_schema.tex").write_text(TIKZ_KG_SCHEMA.strip(), encoding="utf-8")
print("Saved TikZ diagrams in figures/")

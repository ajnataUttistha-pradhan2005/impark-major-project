# Evaluation

Run `python -m backend.evaluation.text_discovery --semantic` for frozen synthetic identity
questions against the imported real catalog. Recall, reciprocal rank, false automatic resolutions
and latency are saved to PostgreSQL and data/evaluation/text_discovery_report.json.
All-source-name recall is separately covered by the opt-in live tests.

models.py retains trace/snapshot evaluation boundaries. A full golden-trace research suite
remains TODO R-014. Allow state-justified alternative actions instead of one fixed agent sequence.
Check recorder loss counters before claiming complete trace reconstruction.

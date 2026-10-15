# Evaluation

Run `python -m backend.evaluation.text_discovery --semantic` for frozen synthetic identity
questions against the imported real catalog. Recall, reciprocal rank, false automatic resolutions
and latency are saved to PostgreSQL and data/evaluation/text_discovery_report.json.
All-source-name recall is separately covered by the opt-in live tests.

`trace_audit.audit_run` checks a captured run's correlation, decision eligibility, agent
start/completion balance, clarification boundary and response-context ordering without requiring
one fixed action sequence. Pass the recorder's dropped/write-failure counters; any loss fails the
audit. Unit scenarios exercise both complete and clarification paths. A broader curated golden-trace
research corpus and viewer remain future work under R-014/R-015.

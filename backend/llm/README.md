# Final response boundary

`LLM_RESPONSE_MODE=guarded` keeps the validated response path below. The optional
`LLM_RESPONSE_MODE=plant_context` selects an experimental, unvalidated freeform
Ollama response. It requires `LLM_PROVIDER=ollama`, `TEXT_SEARCH_ENABLED=true`,
and `NEO4J_ENABLED=true`. The harness loads a read-only, parameterized snapshot
for the session's locked plant, including its details, aliases, parts, uses,
compounds, bioactivities, targets, and linked documents. The snapshot is capped
at 14 KB and divided across categories, so large plants are explicitly marked
truncated. The model may supplement those records with pretrained knowledge.
This mode does not validate factual claims or add citations to model prose;
it can produce unsupported statements. Discovery, plant locking, action policy,
graph read bounds, and safety abstention remain governed by the harness. Switch
back by setting `LLM_RESPONSE_MODE=guarded` and restarting the backend.
When the ordinary text agent cannot classify a question about the locked plant,
the optional mode routes it through a typed plant-details query so the model can
answer from the plant snapshot and its general knowledge. This does not override
scope rejection or health-safety abstention.
The optional text-agent wrapper retains the same search provider interface used
by discovery autocomplete and candidate selection.

The final response component receives only `FinalResponseRequest.response_context`.
It has no repositories, database clients, search tools, or action authority. Graph
evidence is first reduced to allow-listed, cited statements by `verbalize.py`.
`narrative.py` adds a small, fixed set of relationship and assay-term meanings.
It also accepts matching MeSH definitions imported ahead of time from official NLM
records. Those definitions explain named use terms; they never imply the plant
treats the condition or upgrade an evidence class.

With `LLM_PROVIDER=ollama`, the model is asked to write a short explanation
about the supplied statements. It returns structured JSON with fact IDs for
each sentence. The
complete JSON is validated **before any prose is sent to the client**. Validation
checks the cited IDs, named entities, numbers, evidence class, unsupported
medical and assay-strength claims, new substantive vocabulary, unsupported
absence claims, and internal-system language. The server adds
citation markers from real evidence IDs. A rejected or timed-out draft uses the
deterministic `concise.py` explanation; it never exposes the unsafe draft.
After three consecutive rejected or unavailable drafts, the provider uses the
fast deterministic path for two minutes, then probes the model again. This
avoids paying the local-model latency on every turn during a bad run.
The response context carries an `answer_style` derived from the user's wording,
so explanation follow-ups lead with the meaning of a relationship and fewer examples.
Explicitly named terms rank ahead of unrelated graph rows in the answer packet;
ties retain their original order, and the underlying evidence state is unchanged.
The text agent retains recent query types for elliptical follow-ups such as
“explain those” while the one-plant session lock remains authoritative.
Named-use definitions and protein-target measurement questions resolve to
plant-scoped, typed graph queries rather than an unscoped search.

This is a conservative lexical validator, not a proof of semantic entailment.
The local 4B models tested can invent treatment claims and assay interpretations
despite a strict prompt. The deterministic fallback is therefore an essential
part of the response path, and model acceptance should be measured on the
project's evaluation set. `grounded.py` remains available as a fully
deterministic provider. Model choice is configured in `.env`; it does not change
the response boundary or the API contract.

For an explicit explanation follow-up, `knowledge_explanation.py` uses the same
deterministic response context but asks the model for brief general scientific
background per retrieved fact. The cited fact is rendered by the server; the
model's note appears separately as general context and carries no source
citation. Validation rejects new measurements, links, unsourced named entities,
plant-specific effects, treatment/dosage claims, and internal-system language;
unsafe sentences are dropped before streaming. If nothing safe remains, the
existing grounded answer is used. This reduces hallucination risk but cannot
verify pretrained knowledge. General context must not be presented as verified
experimental evidence.

On the 4 GB RTX 3050, `gemma3:4b` (3.4 GB download) ran partly on the CPU and
took roughly 15–22 seconds per short warm answer in a two-question local probe.
It made unsupported inferences about binding strength, so it is not the default
demo model. Keep the currently configured model or use `grounded` for predictable
latency. Run `python -m backend.llm.admin benchmark` against the local system
when evaluating a new model; synthetic probes alone do not establish quality.
> **Current architecture note (2026-10-18).** The active conversation path is the DeepAgents main orchestrator with text/entity, image, and knowledge-graph specialist subagents. Older sections in this file may document retained utilities or earlier behavior; use the [implemented architecture](../../../docs/architecture/README.md) and [file map](../../../docs/repository-map/README.md) for current wiring. The active answer is generated by the main agent; `backend/llm/grounded.py` is the fallback.

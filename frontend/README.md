# Frontend ownership

TODO / DECISION REQUIRED R-001: choose React/Next.js version and package manager before scaffolding
framework-specific app/pages directories. No UI dependencies are installed in this phase.

Feature areas: discovery (name/description/image/text+image/autocomplete), conversation with active
plant context, candidate clarification, safe progress, optional restricted trace viewer.
Use the `/dev` OpenAPI surface only for local integration; R-004 public routes are not frozen.
Do not implement orchestration decisions in the client. Streaming protocol models live in
`backend/contracts/response.py`; transport is R-003. No hidden prompts/reasoning belong in the UI.

Current policy: one plant per chat. Display `ChatResponse.session_notice` before discovery input
and keep the active plant visible in conversation. `SCOPE_REJECTED` responses and HTTP 409
`PLANT_SCOPE_LOCKED` require a new-chat action, not replacement of the current plant. Preserve
an initial question when submitting an autocomplete selection. See GRAPH_AGENT_GUIDE.md.

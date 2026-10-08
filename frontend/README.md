# Frontend ownership

TODO / DECISION REQUIRED R-001: choose React/Next.js version and package manager before scaffolding
framework-specific app/pages directories. No UI dependencies are installed in this phase.

Feature areas: discovery (name/description/image/text+image/autocomplete), conversation with active
plant context, candidate clarification, safe progress, optional restricted trace viewer.
Use the `/dev` OpenAPI surface only for local integration; R-004 public routes are not frozen.
Do not implement orchestration decisions in the client. Streaming protocol models live in
`backend/contracts/response.py`; transport is R-003. No hidden prompts/reasoning belong in the UI.

# Final response ownership

`LLMProvider.generate` receives only `FinalResponseRequest.response_context`. Future Ollama/vLLM
adapters must not receive repositories, tools, actions or mutable state. The placeholder produces
an explicit unconfigured message with educational-use wording. The harness validates citation IDs.

TODO: before enabling a real generative provider, validate claim/evidence-class fidelity and safe
response policy (including model-generated prose). A prompt alone is not an enforcement boundary.
No vendor adapter or model is selected in this phase.

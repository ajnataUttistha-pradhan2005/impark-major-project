"""Per-role chat-model construction. Credentials stay in provider environment variables."""

from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from backend.config.settings import Settings

Role = Literal["main", "text", "image", "graph"]


class AgentModelFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._models: dict[Role, BaseChatModel] = {}

    def get(self, role: Role) -> BaseChatModel:
        if role in self._models:
            return self._models[role]
        provider = (
            (
                getattr(self.settings, f"agent_{role}_model_provider", None)
                or self.settings.agent_main_model_provider
            )
            .strip()
            .lower()
        )
        model_name = (
            getattr(self.settings, f"agent_{role}_model", None)
            or self.settings.agent_main_model
            or self.settings.llm_model
        )
        if not model_name:
            raise ValueError(f"No model configured for {role} agent")
        if provider == "ollama":
            model = ChatOllama(
                model=model_name,
                base_url=self.settings.ollama_base_url or "http://127.0.0.1:11434",
                temperature=0,
                reasoning=False,
                num_ctx=self.settings.llm_context_tokens,
                num_predict=max(self.settings.llm_output_tokens, 1024 if role == "main" else 384),
            )
        else:
            # Provider packages and secrets are installed/configured separately.
            # init_chat_model accepts provider-qualified models without changing agents.
            model = init_chat_model(model_name, model_provider=provider, temperature=0)
        self._models[role] = model
        return model

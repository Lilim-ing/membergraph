from .base import LLM, LLMResult

__all__ = ["LLM", "LLMResult", "build_llm"]


def build_llm(provider: str = "fake", **kwargs):
    provider = (provider or "fake").lower()
    if provider == "fake":
        from .fake import FakeLLM

        return FakeLLM()
    if provider in {"deepseek", "openai", "compat"}:
        from .openai_compat import OpenAICompatLLM

        model = kwargs.pop(
            "model", "deepseek-chat" if provider == "deepseek" else "gpt-4o-mini"
        )
        return OpenAICompatLLM(model=model, **kwargs)
    raise ValueError(f"unknown provider {provider!r}; use 'fake' or 'deepseek'")

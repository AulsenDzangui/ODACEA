from llm.litellm_provider import LiteLLMProvider, friendly_llm_error, llm_error_info

__all__ = ["LiteLLMProvider", "friendly_llm_error", "llm_error_info", "get_provider"]


def get_provider(
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LiteLLMProvider:
    return LiteLLMProvider(model=model, api_key=api_key, base_url=base_url)

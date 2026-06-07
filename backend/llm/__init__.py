from llm.litellm_provider import LiteLLMProvider


def get_provider(
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LiteLLMProvider:
    return LiteLLMProvider(model=model, api_key=api_key, base_url=base_url)

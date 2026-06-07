import os
from datetime import datetime

import litellm
from litellm import completion
from llm.base import LLMProvider

# Laisse LiteLLM retirer silencieusement les paramètres non supportés par le
# provider cible (ex. stream_options.include_usage que certains serveurs locaux
# — Ollama natif notamment — n'acceptent pas). Évite de régresser le streaming
# sur les modèles locaux, cœur de cible de l'application.
litellm.drop_params = True


def _normalize_usage(usage) -> dict:
    """Normalise l'objet usage LiteLLM (forme OpenAI) en dict simple.

    Clés : input_tokens, output_tokens, total_tokens, cache_read_tokens,
    reasoning_tokens. Les détails (cache, raisonnement) sont optionnels selon
    le provider. Aligné sur le LlmUsage de la version web.
    """
    def _get(obj, name):
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    out: dict = {
        "input_tokens": _get(usage, "prompt_tokens"),
        "output_tokens": _get(usage, "completion_tokens"),
        "total_tokens": _get(usage, "total_tokens"),
        "cache_read_tokens": None,
        "reasoning_tokens": None,
    }

    prompt_details = _get(usage, "prompt_tokens_details")
    if prompt_details is not None:
        out["cache_read_tokens"] = _get(prompt_details, "cached_tokens")

    completion_details = _get(usage, "completion_tokens_details")
    if completion_details is not None:
        out["reasoning_tokens"] = _get(completion_details, "reasoning_tokens")

    return out


def _log_request(model: str, system_prompt: str, user_message: str) -> None:
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"logs/llm_{timestamp}.log"
    sep = "=" * 80
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            f"{sep}\n"
            f"[{datetime.now().isoformat(timespec='seconds')}] MODEL: {model}\n"
            f"{sep}\n"
            f"--- SYSTEM ({len(system_prompt)} chars) ---\n{system_prompt}\n\n"
            f"--- USER ({len(user_message)} chars) ---\n{user_message}\n"
            f"{sep}\n"
        )


class LiteLLMProvider(LLMProvider):

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or None
        self.base_url = base_url or None
        self.model = self._effective_model(model, self.base_url)
        # Usage du dernier appel streamé (rempli par stream_with_reasoning quand
        # le serveur renvoie un bloc usage final). None si indisponible.
        self.last_usage: dict | None = None
        # Message d'erreur du dernier validate_connection() en échec (sinon None).
        self.last_error: str | None = None

    # ── API publique ───────────────────────────────────────────────────────────

    def complete(self, system_prompt: str, user_message: str) -> str:
        response = completion(
            model=self.model,
            messages=self._build_messages(system_prompt, user_message),
            **self._kwargs(),
        )
        return response.choices[0].message.content

    def stream(self, system_prompt: str, user_message: str):
        for chunk in completion(
            model=self.model,
            messages=self._build_messages(system_prompt, user_message),
            stream=True,
            **self._kwargs(),
        ):
            yield chunk.choices[0].delta.content or ""

    def stream_with_reasoning(self, system_prompt: str, user_message: str):
        """Yields (is_thinking: bool, chunk: str). Enables extended thinking for capable models.

        Après épuisement du générateur, ``self.last_usage`` contient l'usage tokens
        réel renvoyé par le serveur (entrée/sortie/total + détails cache et
        raisonnement), ou None si le serveur ne le fournit pas.
        """
        self.last_usage = None
        kwargs = self._kwargs()
        # stream_options.include_usage : demande le bloc usage final (OpenAI,
        # LM Studio, vLLM…). LiteLLM le traduit pour les autres providers ;
        # Anthropic renvoie l'usage nativement sur le dernier chunk.
        kwargs["stream_options"] = {"include_usage": True}
        model_lower = self.model.lower()
        thinking_enabled = any(
            p in model_lower for p in ("claude-3-7", "claude-opus-4", "claude-sonnet-4", "claude-haiku-4")
        )
        if thinking_enabled:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8000}
            kwargs.setdefault("max_tokens", 16000)

        for chunk in completion(
            model=self.model,
            messages=self._build_messages(system_prompt, user_message),
            stream=True,
            **kwargs,
        ):
            # Le bloc usage arrive en général sur le dernier chunk (sans choices).
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                self.last_usage = _normalize_usage(usage)
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            # Claude extended thinking OR DeepSeek R1 / Qwen reasoning_content
            thinking = getattr(delta, "thinking", None) or getattr(delta, "reasoning_content", None)
            if thinking:
                yield True, thinking
            if delta.content:
                yield False, delta.content

    def validate_connection(self) -> bool:
        try:
            self.complete("You are a helpful assistant.", "Reply with OK.")
            self.last_error = None
            return True
        except Exception as e:
            # On conserve le message complet (souvent l'erreur LiteLLM la plus
            # parlante : provider inconnu, clé manquante, serveur injoignable…)
            # pour le remonter à l'UI au lieu d'un « Échec » opaque.
            self.last_error = f"{type(e).__name__}: {e}"
            return False

    # ── Helpers privés ─────────────────────────────────────────────────────────

    @staticmethod
    def _effective_model(model: str, base_url: str | None) -> str:
        """Route un serveur local **sans préfixe** vers le provider compatible OpenAI.

        Un serveur local (`base_url` renseigné — LM Studio, JAN, llama.cpp, Ollama
        sur `/v1`…) expose une API compatible OpenAI. LiteLLM exige un préfixe de
        provider pour router ; sans lui, il lève « LLM Provider NOT provided ».
        On préfixe donc `openai/` quand un `base_url` est présent et que le modèle
        n'a pas déjà de préfixe (`provider/...`). L'utilisateur n'a ainsi rien à
        préfixer, et le modèle déjà chargé par le serveur est utilisé tel quel.
        Un préfixe explicite (`ollama/...`, `openai/...`, `gemini/...`) est respecté.
        """
        m = (model or "").strip()
        if base_url and "/" not in m:
            return f"openai/{m}" if m else "openai/local-model"
        return m

    def _build_messages(self, system_prompt: str, user_message: str) -> list[dict]:
        _log_request(self.model, system_prompt, user_message)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]

    def _kwargs(self) -> dict:
        kwargs = {}
        if self.base_url:
            kwargs["api_base"] = self.base_url
            # Serveurs locaux (LM Studio, Ollama, JAN) exigent une clé non vide
            kwargs["api_key"] = self.api_key or "lm-studio"
            kwargs["timeout"] = 3600  # 1 h pour les modèles locaux
        elif self.api_key:
            kwargs["api_key"] = self.api_key
            # Modèles cloud (Anthropic, OpenAI, Gemini…) : 30 min couvre les
            # modèles de raisonnement (o1, o3, DeepSeek-R1) sur de gros vracs.
            # Le défaut LiteLLM (~10 min) est trop court dans ces cas.
            kwargs["timeout"] = 1800
        return kwargs

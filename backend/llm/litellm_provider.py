import functools
import os
import re
import time
from collections.abc import Callable
from datetime import datetime

import litellm
from litellm import completion

from llm.base import LLMProvider

# Clés d'API (OpenAI `sk-`/`sk-proj-`, Anthropic `sk-ant-`…) éventuellement
# présentes dans un message d'erreur du fournisseur — à masquer avant affichage.
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}", re.IGNORECASE)

# Repli si `litellm.provider_list` disparaît ou change de forme : les préfixes
# effectivement documentés et utilisés par le projet. Volontairement court — il
# ne sert qu'à ne pas casser le routage si l'introspection échoue.
_FALLBACK_PROVIDER_PREFIXES = frozenset(
    {"openai", "anthropic", "gemini", "ollama", "azure", "bedrock", "vertex_ai"}
)


@functools.lru_cache(maxsize=1)
def _litellm_provider_prefixes() -> frozenset[str]:
    """Préfixes de provider reconnus par LiteLLM, en minuscules.

    Lu depuis `litellm.provider_list` (liste d'énumérés) pour rester juste quand
    LiteLLM ajoute des fournisseurs, plutôt que de figer une liste qui dériverait.
    """
    try:
        prefixes = {
            str(getattr(p, "value", p)).strip().lower() for p in litellm.provider_list
        }
        return frozenset(prefixes) if prefixes else _FALLBACK_PROVIDER_PREFIXES
    except Exception:
        return _FALLBACK_PROVIDER_PREFIXES


def _is_litellm(e: Exception, attr: str) -> bool:
    cls = getattr(litellm, attr, None)
    return isinstance(cls, type) and isinstance(e, cls)


def llm_error_info(e: Exception) -> dict:
    """Traduit une exception LiteLLM en erreur structurée `{message, code, hint}`.

    Taxonomie : `code` est stable (exploitable par le
    front et les tests), `hint` est l'action recommandée à l'utilisateur. Le
    message ne divulgue **jamais** de matériel sensible (clé d'API) ni les
    internes du fournisseur (le `str(e)` de LiteLLM contient typiquement la clé
    sur une erreur d'auth). Repli générique sinon (type seul, première ligne
    expurgée et tronquée)."""
    status = getattr(e, "status_code", None)
    name = type(e).__name__

    def _is(attr: str) -> bool:
        return _is_litellm(e, attr)

    if _is("AuthenticationError") or status == 401:
        return {
            "message": "Clé API invalide ou manquante pour ce modèle.",
            "code": "llm_auth",
            "hint": "Renseignez ou corrigez la clé API dans les réglages (panneau latéral).",
        }
    if _is("PermissionDeniedError") or status == 403:
        return {
            "message": "Accès refusé par le fournisseur LLM (clé sans droit sur ce modèle ?).",
            "code": "llm_forbidden",
            "hint": "Vérifiez que votre clé donne accès à ce modèle, ou choisissez-en un autre.",
        }
    if _is("NotFoundError") or status == 404:
        return {
            "message": "Modèle introuvable : vérifiez son identifiant.",
            "code": "llm_model_not_found",
            "hint": "Contrôlez l'orthographe de l'identifiant du modèle (ex. gpt-5.1, ollama/qwen3:14b).",
        }
    if _is("RateLimitError") or status == 429:
        return {
            "message": "Limite de débit atteinte côté fournisseur LLM.",
            "code": "llm_rate_limit",
            "hint": "Patientez quelques instants puis relancez ; réduisez la taille des lots si cela se répète.",
        }
    if _is("ContextWindowExceededError"):
        return {
            "message": "Le contenu dépasse la fenêtre de contexte du modèle.",
            "code": "llm_context_window",
            "hint": "Activez l'échantillonnage des items, le filtrage des colonnes, ou découpez le classement en lots plus petits.",
        }
    if _is("Timeout") or _is("APIConnectionError") or _is("ServiceUnavailableError"):
        return {
            "message": "Serveur LLM injoignable ou délai dépassé.",
            "code": "llm_unreachable",
            "hint": "Vérifiez que le serveur (LM Studio, Ollama…) est lancé et que l'URL est correcte ; pour un modèle cloud, vérifiez la connexion réseau.",
        }
    if _is("BadRequestError") or status == 400:
        return {
            "message": "Requête refusée par le fournisseur LLM.",
            "code": "llm_bad_request",
            "hint": "Vérifiez le modèle choisi et les options ; consultez le détail ci-dessous le cas échéant.",
        }
    raw = _KEY_RE.sub("[clé masquée]", str(e)).strip().splitlines()
    detail = raw[0][:200] if raw else ""
    return {
        "message": f"Erreur du service LLM ({name})" + (f" : {detail}" if detail else "") + ".",
        "code": "llm_unknown",
        "hint": "Réessayez ; si l'erreur persiste, testez la connexion depuis les réglages.",
    }


def friendly_llm_error(e: Exception) -> str:
    """Message court et sûr pour l'utilisateur (cf. `llm_error_info`)."""
    return llm_error_info(e)["message"]


# Délais (secondes) entre tentatives sur erreur transitoire. Deux retries
# maximum : au-delà, le problème n'est plus transitoire.
RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0)


def _is_transient_error(e: Exception) -> bool:
    """Erreur qui justifie un réessai automatique : aléa réseau, délai dépassé,
    429 ou 5xx (serveur local saturé, redémarrage…). Jamais une erreur de
    contenu (auth, modèle introuvable, requête refusée, fenêtre de contexte) :
    la relancer à l'identique reproduirait l'échec."""
    status = getattr(e, "status_code", None)
    if status in (408, 429, 500, 502, 503, 504):
        return True
    return any(
        _is_litellm(e, attr)
        for attr in (
            "Timeout",
            "APIConnectionError",
            "ServiceUnavailableError",
            "InternalServerError",
            "RateLimitError",
        )
    )

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
    # En démonstration, on n'écrit aucun journal de requête (minimisation des
    # données / pas d'écriture disque sur l'hébergement éphémère).
    if os.getenv("DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on"):
        return
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
        # Visibilité du retry : callback appelé avec un message lisible à
        # chaque nouvelle tentative (CLI → stderr, API → événement SSE notice),
        # et compteur de retries du dernier appel streamé.
        self.on_retry: Callable[[str], None] | None = None
        self.last_retries = 0

    # ── API publique ───────────────────────────────────────────────────────────

    def complete(
        self, system_prompt: str, user_message: str, *, cache_user_boundary: str | None = None
    ) -> str:
        response = completion(
            model=self.model,
            messages=self._build_messages(system_prompt, user_message, cache_user_boundary),
            **self._kwargs(),
        )
        return response.choices[0].message.content

    def complete_with_tools(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> dict:
        """Un tour de boucle agent : messages complets (multi-tours, résultats
        d'outils inclus), déclaration d'outils facultative (function calling natif).

        Renvoie ``{"content": str, "tool_calls": [{"id", "name", "arguments"}]}``
        (``arguments`` est la chaîne JSON brute du fournisseur — parsée par la
        boucle, qui renvoie l'erreur au modèle si elle est invalide). Sans
        ``tools`` (repli JSON des petits modèles locaux), c'est une complétion
        ordinaire. Non streamé : un pas d'agent est court (un appel d'outil ou
        une réponse) ; l'usage réel est exposé sur ``last_usage``. Retry B9 sur
        erreur transitoire (l'appel est sans effet de bord, rejouable).
        """
        self.last_usage = None
        self.last_retries = 0
        kwargs = self._kwargs()
        if tools:
            kwargs["tools"] = tools
        msgs = self._cache_system_message(messages)
        while True:
            try:
                response = completion(model=self.model, messages=msgs, **kwargs)
                break
            except Exception as e:
                if self.last_retries >= len(RETRY_DELAYS) or not _is_transient_error(e):
                    raise
                delay = RETRY_DELAYS[self.last_retries]
                self.last_retries += 1
                if self.on_retry:
                    self.on_retry(
                        f"Erreur transitoire du serveur LLM ({type(e).__name__}) — "
                        f"nouvelle tentative {self.last_retries}/{len(RETRY_DELAYS)} "
                        f"dans {delay:g} s."
                    )
                time.sleep(delay)
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage = _normalize_usage(usage)
        msg = response.choices[0].message
        calls = [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments or "{}"}
            for tc in (getattr(msg, "tool_calls", None) or [])
        ]
        return {"content": msg.content or "", "tool_calls": calls}

    def _cache_system_message(self, messages: list[dict]) -> list[dict]:
        """Cache de prompt Anthropic sur la boucle agent : le system prompt
        (rôle + digest du vrac) est identique à chaque tour de la session — on le
        marque `cache_control: ephemeral` pour un modèle Anthropic direct. Tout
        autre fournisseur reçoit les messages inchangés (cf. `_build_messages`)."""
        if self.base_url or not self._is_anthropic(self.model):
            return messages
        out = []
        for m in messages:
            if m.get("role") == "system" and isinstance(m.get("content"), str):
                m = {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": m["content"],
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            out.append(m)
        return out

    def stream(
        self, system_prompt: str, user_message: str, *, cache_user_boundary: str | None = None
    ):
        for chunk in completion(
            model=self.model,
            messages=self._build_messages(system_prompt, user_message, cache_user_boundary),
            stream=True,
            **self._kwargs(),
        ):
            yield chunk.choices[0].delta.content or ""

    def stream_with_reasoning(
        self, system_prompt: str, user_message: str, *, cache_user_boundary: str | None = None
    ):
        """Yields (is_thinking: bool, chunk: str). Enables extended thinking for capable models.

        Après épuisement du générateur, ``self.last_usage`` contient l'usage tokens
        réel renvoyé par le serveur (entrée/sortie/total + détails cache et
        raisonnement), ou None si le serveur ne le fournit pas.

        Retry automatique : sur erreur transitoire (réseau, timeout, 429,
        5xx) survenant **avant le premier chunk**, jusqu'à ``len(RETRY_DELAYS)``
        nouvelles tentatives avec backoff. Une erreur après début de réponse
        n'est jamais retentée (la réponse partielle serait perdue/dupliquée) ;
        une erreur de contenu non plus. Chaque tentative est signalée via
        ``self.on_retry`` et comptée dans ``self.last_retries``.
        """
        self.last_usage = None
        self.last_retries = 0
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

        messages = self._build_messages(system_prompt, user_message, cache_user_boundary)
        while True:
            yielded = False
            try:
                for item in self._stream_attempt(messages, kwargs):
                    yielded = True
                    yield item
                return
            except Exception as e:
                if (
                    yielded
                    or self.last_retries >= len(RETRY_DELAYS)
                    or not _is_transient_error(e)
                ):
                    raise
                delay = RETRY_DELAYS[self.last_retries]
                self.last_retries += 1
                if self.on_retry:
                    self.on_retry(
                        f"Erreur transitoire du serveur LLM ({type(e).__name__}) — "
                        f"nouvelle tentative {self.last_retries}/{len(RETRY_DELAYS)} "
                        f"dans {delay:g} s."
                    )
                time.sleep(delay)

    def _stream_attempt(self, messages: list[dict], kwargs: dict):
        """Une tentative de streaming (cf. stream_with_reasoning)."""
        for chunk in completion(
            model=self.model,
            messages=messages,
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
            # Message traduit et **expurgé** : le str(e) brut de LiteLLM contient
            # typiquement la clé d'API sur une erreur d'auth. friendly_llm_error
            # donne un motif clair (clé invalide, modèle introuvable, serveur
            # injoignable…) sans fuite.
            self.last_error = friendly_llm_error(e)
            return False

    # ── Helpers privés ─────────────────────────────────────────────────────────

    @staticmethod
    def _effective_model(model: str, base_url: str | None) -> str:
        """Route un serveur compatible OpenAI **sans préfixe** vers le provider `openai`.

        Un serveur joint par `base_url` (LM Studio, JAN, llama.cpp, Ollama sur
        `/v1`, mais aussi une passerelle distante vLLM / TGI / LiteLLM Proxy /
        OpenRouter) expose une API compatible OpenAI. LiteLLM exige un préfixe de
        provider pour router ; sans lui, il lève « LLM Provider NOT provided ».

        On préfixe donc `openai/` dès qu'un `base_url` est présent, **sauf** si le
        premier segment du nom est déjà un provider connu de LiteLLM
        (`ollama/…`, `openai/…`, `gemini/…` : préfixe explicite, respecté).

        Le test porte sur le provider, pas sur la simple présence d'un `/` : la
        convention HuggingFace `organisation/modèle` — la norme sur les
        passerelles vLLM — contient un `/` sans être un préfixe de provider.
        Sans cette distinction, `mistralai/Mistral-Small-3.2-24B-Instruct-2506`
        partait tel quel et LiteLLM prenait `mistralai` pour un fournisseur.

        Ambiguïté résiduelle assumée : une organisation HuggingFace homonyme d'un
        provider (`openai/gpt-oss-120b`) est lue comme un préfixe explicite et
        n'est donc pas re-préfixée — comportement historique, et seule lecture
        possible sans deviner l'intention.
        """
        m = (model or "").strip()
        if not base_url:
            return m
        if not m:
            return "openai/local-model"
        head = m.split("/", 1)[0].lower() if "/" in m else ""
        if head and head in _litellm_provider_prefixes():
            return m
        return f"openai/{m}"

    @staticmethod
    def _is_anthropic(model: str) -> bool:
        """Le modèle est-il servi par Anthropic en direct ? (cache de prompt)

        LiteLLM route `claude-*` et `anthropic/*` vers Anthropic. On exclut les
        serveurs locaux (`base_url` présent → géré par l'appelant) : seul
        Anthropic comprend `cache_control`."""
        m = (model or "").lower()
        return m.startswith("claude") or m.startswith("anthropic/")

    def _build_messages(
        self, system_prompt: str, user_message: str, cache_user_boundary: str | None = None
    ) -> list[dict]:
        """Construit les messages LiteLLM.

        Cache de prompt Anthropic : pour un modèle Anthropic en direct (pas
        de `base_url`), le **system prompt** — identique d'un lot à l'autre — est
        marqué `cache_control: ephemeral` ; si `cache_user_boundary` est fourni
        (CLA-001 : `CLA_001.CACHE_BOUNDARY`), le **préfixe stable du user
        message** (le plan validé, identique entre lots) l'est aussi. Sur les
        gros vracs multi-lots, Anthropic ne refacture alors plus le préfixe
        (system + plan) à chaque lot. Pour tout autre fournisseur (OpenAI,
        Gemini, serveurs locaux), on conserve **strictement** les messages en
        chaînes simples — aucun changement de comportement."""
        _log_request(self.model, system_prompt, user_message)
        if self.base_url or not self._is_anthropic(self.model):
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ]
        return [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "user", "content": self._user_content_with_cache(user_message, cache_user_boundary)},
        ]

    @staticmethod
    def _user_content_with_cache(user_message: str, boundary: str | None):
        """Découpe le user message au marqueur `boundary` et marque le préfixe
        (le plan validé) comme cacheable. Repli sur la chaîne simple si le
        marqueur est absent, en tête, ou si le préfixe est vide."""
        if boundary:
            idx = user_message.find(boundary)
            if idx > 0 and user_message[:idx].strip():
                return [
                    {
                        "type": "text",
                        "text": user_message[:idx],
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": user_message[idx:]},
                ]
        return user_message

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

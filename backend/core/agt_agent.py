"""Boucle agent de l'exploration de vrac.

Agent **lecture seule** : il aide à chercher et naviguer dans le fonds, jamais
à le modifier (pas de classement, pas de renommage, pas de mémorisation de
faits). Le modèle ne reçoit **jamais le CSV** : uniquement le résumé compact du
vrac (digest `audit_scan`, dans le system prompt) et les résultats d'outils —
paginés/totalisés par `core.agt_tools`. Deux modes, choisis par tour :

* **natif** : function calling du fournisseur (schémas `prompts.AGT_001.TOOLS`),
  boucle OpenAI standard (assistant→tool_calls, tool→résultat JSON) ;
* **json** (repli, risque n°1 du lot) : les petits modèles locaux au
  tool-calling faible produisent UN objet JSON par tour (`{"outil": …}` ou
  `{"reponse": …}`), parsé avec tolérance ; une sortie invalide reçoit une
  relance corrective, puis est traitée comme réponse finale (dégradation douce,
  jamais de chiffre inventé par le code).

`tool_mode="auto"` : natif pour un modèle cloud, json pour un serveur local
(`base_url` renseigné ou préfixe local — `core.pricing.is_local`).

La boucle est un générateur d'événements dicts (l'API les traduit en SSE, la
transparence affiche chaque appel d'outil) :

    {"type": "tool",       "step", "name", "arguments"}
    {"type": "toolResult", "step", "name", "result"}
    {"type": "answer",     "text"}
    {"type": "final",      "answer", "steps", "usage"}   # usage = tour courant
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from core import agt_tools
from core.agt_session import AgentSession, add_usage
from core.pricing import is_local
from prompts import AGT_001

# Garde-fou de la boucle : au-delà, on demande au modèle de conclure avec ce
# qu'il a (un tour d'exploration légitime tient largement en dessous).
MAX_STEPS = 8

# Historique compact conservé sur la session : les derniers échanges
# user/assistant, sans le trafic d'outils (reconstruisible en re-questionnant).
MAX_HISTORY_MESSAGES = 12

# Outils de requête (lecture seule) : appelés sur le DataFrame. L'agent
# n'a plus aucun autre outil — plus de mutation possible (classement/notes
# retirés).
_TOOL_REGISTRY: dict[str, Callable[..., dict]] = {
    "chercher": agt_tools.chercher,
    "lister_dossier": agt_tools.lister_dossier,
    "compter": agt_tools.compter,
    "echantillonner": agt_tools.echantillonner,
    "stats": agt_tools.stats,
    "mots_frequents": agt_tools.mots_frequents,
}


class ToolProvider(Protocol):
    """Le sous-ensemble de LiteLLMProvider consommé par la boucle."""

    last_usage: dict | None

    def complete_with_tools(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> dict: ...


def resolve_tool_mode(mode: str, model: str, base_url: str | None) -> str:
    """`auto` → `json` pour un serveur local (tool-calling souvent faible sur
    les petits modèles), `native` pour un cloud. `native`/`json` explicites
    sont respectés."""
    if mode in ("native", "json"):
        return mode
    return "json" if is_local(model, base_url) else "native"


def run_tool(session: AgentSession, name: str, arguments: dict) -> dict:
    """Exécute un outil de requête sur le DataFrame — ne lève jamais :
    l'erreur (outil inconnu, argument invalide) est renvoyée au modèle, qui
    peut se corriger."""
    fn = _TOOL_REGISTRY.get(name)
    if fn is None:
        tools = ", ".join(sorted(_TOOL_REGISTRY))
        return {"erreur": f"Outil inconnu : {name}. Outils : {tools}."}
    if not isinstance(arguments, dict):
        return {"erreur": "Les arguments doivent être un objet JSON."}
    try:
        return fn(session.df, **arguments)
    except TypeError as e:
        return {"erreur": f"Arguments invalides pour {name} : {e}"}
    except Exception as e:  # défense en profondeur : jamais de 500 sur un tour
        return {"erreur": f"Échec de l'outil {name} ({type(e).__name__}) : {e}"}


def _tool_result_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


def _parse_json_action(content: str) -> dict | None:
    """Extrait le premier objet JSON équilibré d'une sortie de modèle (fences
    Markdown et préambule tolérés). None si aucun objet parsable."""
    text = content.strip()
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
                    break
        start = text.find("{", start + 1)
    return None


def _update_history(session: AgentSession, question: str, answer: str) -> None:
    session.history.append({"role": "user", "content": question})
    session.history.append({"role": "assistant", "content": answer})
    del session.history[:-MAX_HISTORY_MESSAGES]


def agent_turn(
    session: AgentSession,
    question: str,
    provider: ToolProvider,
    tool_mode: str = "native",
) -> Iterator[dict]:
    """Un tour de dialogue : question de l'archiviste → (appels d'outils)* →
    réponse. Cumule l'usage tokens sur la session."""
    if tool_mode == "json":
        yield from _turn_json(session, question, provider)
    else:
        yield from _turn_native(session, question, provider)


def _turn_usage(provider: ToolProvider, session: AgentSession, turn_usage: dict) -> None:
    add_usage(session, provider.last_usage)
    if provider.last_usage:
        for k, v in provider.last_usage.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                turn_usage[k] = (turn_usage.get(k) or 0) + v


def _finalize(
    session: AgentSession, question: str, answer: str, steps: int, turn_usage: dict
) -> dict:
    _update_history(session, question, answer)
    return {
        "type": "final",
        "answer": answer,
        "steps": steps,
        "usage": turn_usage or None,
    }


_CONCLUDE_MSG = (
    "Limite d'appels d'outils atteinte pour ce tour : formulez maintenant votre "
    "meilleure réponse avec les résultats déjà obtenus (en signalant ce qui "
    "resterait à vérifier)."
)


def _system_prompt(session: AgentSession, json_mode: bool) -> str:
    """Le system prompt du tour : rôle + digest (+ rapport d'audit du projet si
    la session en porte un, 0.6.0) — préfixe stable."""
    return AGT_001.build_system_prompt(
        session.digest, json_mode=json_mode, audit_report=session.audit_report
    )


def _turn_native(
    session: AgentSession, question: str, provider: ToolProvider
) -> Iterator[dict]:
    system = _system_prompt(session, json_mode=False)
    messages: list[dict] = [
        {"role": "system", "content": system},
        *session.history,
        {"role": "user", "content": question},
    ]
    turn_usage: dict = {}
    for step in range(1, MAX_STEPS + 1):
        result = provider.complete_with_tools(messages, tools=AGT_001.TOOLS)
        _turn_usage(provider, session, turn_usage)
        calls = result["tool_calls"]
        if not calls:
            answer = result["content"].strip()
            if answer:
                yield {"type": "answer", "text": answer}
            yield _finalize(session, question, answer, step, turn_usage)
            return
        # Rejoue le message assistant tel que le protocole OpenAI l'attend,
        # puis un message `tool` par appel.
        messages.append(
            {
                "role": "assistant",
                "content": result["content"] or None,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in calls
                ],
            }
        )
        for call in calls:
            try:
                arguments: Any = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError as e:
                arguments = None
                tool_result: dict = {"erreur": f"Arguments JSON invalides : {e}"}
            if arguments is not None:
                yield {
                    "type": "tool", "step": step,
                    "name": call["name"], "arguments": arguments,
                }
                tool_result = run_tool(session, call["name"], arguments)
            yield {
                "type": "toolResult", "step": step,
                "name": call["name"], "result": tool_result,
            }
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": _tool_result_text(tool_result),
                }
            )
    # MAX_STEPS atteint : un dernier appel sans outils pour conclure proprement.
    messages.append({"role": "user", "content": _CONCLUDE_MSG})
    result = provider.complete_with_tools(messages, tools=None)
    _turn_usage(provider, session, turn_usage)
    answer = result["content"].strip()
    if answer:
        yield {"type": "answer", "text": answer}
    yield _finalize(session, question, answer, MAX_STEPS + 1, turn_usage)


_JSON_RETRY_MSG = (
    "Réponse invalide : répondez par UN seul objet JSON — "
    '{"outil": "<nom>", "arguments": {…}} pour appeler un outil, ou '
    '{"reponse": "…"} pour répondre à l\'archiviste.'
)


def _turn_json(
    session: AgentSession, question: str, provider: ToolProvider
) -> Iterator[dict]:
    system = _system_prompt(session, json_mode=True)
    messages: list[dict] = [
        {"role": "system", "content": system},
        *session.history,
        {"role": "user", "content": question},
    ]
    turn_usage: dict = {}
    retried_parse = False
    for step in range(1, MAX_STEPS + 1):
        result = provider.complete_with_tools(messages, tools=None)
        _turn_usage(provider, session, turn_usage)
        content = result["content"]
        action = _parse_json_action(content)

        if action is None or ("outil" not in action and "reponse" not in action):
            if not retried_parse:
                # Une relance corrective, puis dégradation douce : la sortie
                # brute devient la réponse (le code n'invente jamais de chiffre).
                retried_parse = True
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": _JSON_RETRY_MSG})
                continue
            answer = content.strip()
            if answer:
                yield {"type": "answer", "text": answer}
            yield _finalize(session, question, answer, step, turn_usage)
            return

        if "reponse" in action:
            answer = str(action.get("reponse", "")).strip()
            if answer:
                yield {"type": "answer", "text": answer}
            yield _finalize(session, question, answer, step, turn_usage)
            return

        name = str(action.get("outil", ""))
        arguments = action.get("arguments") or {}
        yield {"type": "tool", "step": step, "name": name, "arguments": arguments}
        tool_result = run_tool(session, name, arguments)
        yield {"type": "toolResult", "step": step, "name": name, "result": tool_result}
        messages.append({"role": "assistant", "content": content})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Résultat de l'outil {name} :\n{_tool_result_text(tool_result)}\n\n"
                    "Poursuivez (nouvel objet JSON : autre outil, ou réponse finale)."
                ),
            }
        )
    messages.append({"role": "user", "content": _CONCLUDE_MSG + ' Répondez par {"reponse": "…"}.'})
    result = provider.complete_with_tools(messages, tools=None)
    _turn_usage(provider, session, turn_usage)
    action = _parse_json_action(result["content"])
    answer = (
        str(action.get("reponse", "")).strip()
        if action and "reponse" in action
        else result["content"].strip()
    )
    if answer:
        yield {"type": "answer", "text": answer}
    yield _finalize(session, question, answer, MAX_STEPS + 1, turn_usage)

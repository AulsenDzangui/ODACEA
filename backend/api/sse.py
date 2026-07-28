"""Formatage des événements SSE. Chaque message est une ligne `data: <json>`
suivie d'une ligne vide. Le `type` discrimine côté client (client-stream.ts) :

    reasoning  {delta}                     — chunk de raisonnement (thinking)
    text       {delta}                      — chunk de réponse
    progress   {batch, totalBatches, itemsDone}  — avancement du classement par lots
    done       {...payload, durationMs}     — résultat final structuré ; durationMs =
                                              durée de traitement LLM réelle (mesure perf)
    notice     {message}                    — information non bloquante (ex. retry LLM)
    error      {message, code?, hint?}      — erreur (le flux s'arrête) ; `code` est un
                                              identifiant stable de la taxonomie,
                                              `hint` l'action recommandée à l'utilisateur
"""
from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from typing import Any

# Commentaire SSE (ligne débutant par `:`) — ignoré par EventSource et par notre
# parseur front (`client-stream.ts` ne traite que les lignes `data:`). Sert de
# heartbeat : des octets sur le fil empêchent les proxys de couper une connexion
# jugée inactive.
HEARTBEAT = ": ping\n\n"


def event(type_: str, **fields: Any) -> str:
    payload = {"type": type_, **fields}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def reasoning(delta: str) -> str:
    return event("reasoning", delta=delta)


def text(delta: str) -> str:
    return event("text", delta=delta)


def progress(batch: int, total_batches: int, items_done: int) -> str:
    return event("progress", batch=batch, totalBatches=total_batches, itemsDone=items_done)


def done(**payload: Any) -> str:
    return event("done", **payload)


def notice(message: str) -> str:
    return event("notice", message=message)


def error(message: str, code: str | None = None, hint: str | None = None) -> str:
    fields: dict[str, Any] = {"message": message}
    if code:
        fields["code"] = code
    if hint:
        fields["hint"] = hint
    return event("error", **fields)


# Sentinelle de fin de flux dans la file interne de `with_heartbeat`.
_DONE = object()


def with_heartbeat(generator: Iterator[str], interval: float) -> Iterator[str]:
    """Enrobe un générateur SSE en injectant un commentaire `: ping` pendant les
    silences plus longs que `interval` secondes.

    Pourquoi un thread : le générateur source est synchrone et **bloque** sur le
    stream LiteLLM ; pendant une longue réflexion (modèles de raisonnement, avant
    le premier token), aucun octet ne circule et un proxy peut couper. On itère
    donc la source dans un thread de travail qui pousse ses événements dans une
    file ; le générateur rendu lit la file avec un *timeout* et, à chaque silence,
    émet un heartbeat.

    Annulation / réservation démo : à la déconnexion du client, Starlette ferme ce
    générateur (GeneratorExit) ; le `finally` pose `stop`. Le thread, dès le
    prochain événement de la source, rompt l'itération et **ferme la source**
    (`generator.close()`) — ce qui exécute le `finally` du générateur source
    (arrêt de l'itération LiteLLM + remboursement de la réservation démo). La
    latence d'annulation est donc bornée par l'arrivée du prochain chunk, jamais
    pire que l'attente déjà subie côté client.

    `interval <= 0` désactive le heartbeat (passe-plat).
    """
    if interval <= 0:
        yield from generator
        return

    items: queue.Queue[Any] = queue.Queue()
    stop = threading.Event()

    def pump() -> None:
        result: Any = _DONE
        try:
            for item in generator:
                if stop.is_set():
                    break
                items.put(item)
        except BaseException as exc:  # remonté tel quel au consommateur
            result = exc
        finally:
            generator.close()  # exécute le finally de la source (rollback démo)
            items.put(result)

    worker = threading.Thread(target=pump, name="sse-heartbeat", daemon=True)
    worker.start()
    try:
        while True:
            try:
                item = items.get(timeout=interval)
            except queue.Empty:
                yield HEARTBEAT
                continue
            if item is _DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()

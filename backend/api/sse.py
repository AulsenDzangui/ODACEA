"""Formatage des événements SSE. Chaque message est une ligne `data: <json>`
suivie d'une ligne vide. Le `type` discrimine côté client (client-stream.ts) :

    reasoning  {delta}                     — chunk de raisonnement (thinking)
    text       {delta}                      — chunk de réponse
    progress   {batch, totalBatches, itemsDone}  — avancement du classement par lots
    done       {...payload, durationMs}     — résultat final structuré ; durationMs =
                                              durée de traitement LLM réelle (mesure perf)
    error      {message}                    — erreur (le flux s'arrête)
"""
from __future__ import annotations

import json
from typing import Any


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


def error(message: str) -> str:
    return event("error", message=message)

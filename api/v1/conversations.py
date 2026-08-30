"""Conversation history endpoints for the frontend chat workspace."""

from __future__ import annotations

from api.middleware import json_response
from api.workers import TaskWorker


def list_conversations(handler: object, worker: TaskWorker, limit: int = 50) -> None:
    """Return conversation summaries, newest first."""
    json_response(handler, 200, worker.list_conversations(limit))


def get_conversation(handler: object, worker: TaskWorker, conversation_id: str) -> None:
    """Return a complete conversation, including its runs and messages."""
    conversation = worker.conversation(conversation_id)
    if conversation is None:
        json_response(handler, 404, {"error": "conversation not found"})
        return
    json_response(handler, 200, conversation)

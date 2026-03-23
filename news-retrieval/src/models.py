"""Pydantic models for A2A protocol."""
import uuid
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class MessagePart(BaseModel):
    """A single part of an A2A message (e.g. a text segment)."""

    kind: str
    text: Optional[str] = None


class Message(BaseModel):
    """An A2A message composed of one or more parts."""

    role: str
    parts: List[MessagePart]
    messageId: Optional[str] = None


class JsonRpcParams(BaseModel):
    """Parameters for a JSON-RPC 2.0 request to this agent."""

    session_id: Optional[str] = None
    message: Message


class JsonRpcRequest(BaseModel):
    """An incoming JSON-RPC 2.0 request envelope."""

    jsonrpc: Literal["2.0"]
    id: str
    method: str
    params: JsonRpcParams


class ArtifactPart(BaseModel):
    """A single content part within an artifact (defaults to plain text)."""

    kind: str = "text"
    text: str


class Artifact(BaseModel):
    """An output artifact produced by the agent (e.g. a report or answer)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "text"
    parts: List[ArtifactPart]


class TaskStatus(BaseModel):
    """The current state of a task and when it was last updated."""

    state: str
    timestamp: str


class Task(BaseModel):
    """An A2A task, tracking status and any artifacts the agent produced."""

    id: str
    kind: str = "task"
    status: TaskStatus
    artifacts: List[Artifact] = []
    contextId: Optional[str] = None


class JsonRpcResponse(BaseModel):
    """An outgoing JSON-RPC 2.0 response envelope wrapping a completed task."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Task

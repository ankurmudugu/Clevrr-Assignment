from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    store_url: str | None = None


class DataTable(BaseModel):
    title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)


class ChartSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    type: Literal["line", "bar"] = "bar"
    title: str | None = None
    x_key: str = Field(default="label", alias="xKey")
    y_key: str = Field(default="value", alias="yKey")
    data: list[dict[str, Any]] = Field(default_factory=list)


class AgentPayload(BaseModel):
    answer: str
    insights: list[str] = Field(default_factory=list)
    table: DataTable | None = None
    chart: ChartSpec | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    response: AgentPayload

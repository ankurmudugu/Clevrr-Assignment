from __future__ import annotations

import ast
import json
import re

from .models import AgentPayload, DataTable


JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
MARKDOWN_TABLE_RE = re.compile(r"\|.+\|")
EMPTY_ANSWER_MESSAGE = "The agent returned a response, but it did not include a summary sentence."


def coerce_agent_payload(raw_output: str) -> AgentPayload:
    normalized_raw_output = raw_output.strip()
    for candidate in _candidate_payload_strings(normalized_raw_output):
        parsed_payload = _try_parse_payload(candidate, normalized_raw_output)
        if parsed_payload is not None:
            return parsed_payload

    markdown_payload = _try_parse_markdown_table_payload(normalized_raw_output)
    if markdown_payload is not None:
        return markdown_payload

    cleaned_output = normalized_raw_output
    if CODE_FENCE_RE.search(cleaned_output):
        cleaned_output = "The agent returned internal analysis instead of a final answer."

    payload = AgentPayload(
        answer=cleaned_output,
        insights=[],
        metadata={"format_warning": "Agent returned non-JSON output."},
    )
    payload.metadata.setdefault("raw_output", normalized_raw_output)
    return payload


def _fallback_answer(payload: AgentPayload) -> str:
    if payload.insights:
        return payload.insights[0]
    if payload.table and payload.table.rows:
        return "Here is the requested table."
    if payload.chart and payload.chart.data:
        return "Here is the requested chart."
    return EMPTY_ANSWER_MESSAGE


def _candidate_payload_strings(raw_output: str) -> list[str]:
    candidates: list[str] = []
    _append_candidate(candidates, raw_output)

    match = JSON_BLOCK_RE.search(raw_output)
    if match:
        _append_candidate(candidates, match.group(0))

    for fence_match in CODE_FENCE_RE.finditer(raw_output):
        _append_candidate(candidates, fence_match.group(1))
        inner_match = JSON_BLOCK_RE.search(fence_match.group(1))
        if inner_match:
            _append_candidate(candidates, inner_match.group(0))

    try:
        literal_value = ast.literal_eval(raw_output)
    except (SyntaxError, ValueError):
        literal_value = None

    if isinstance(literal_value, str):
        _append_candidate(candidates, literal_value)
    elif isinstance(literal_value, list):
        for item in literal_value:
            if isinstance(item, str):
                _append_candidate(candidates, item)
                for fence_match in CODE_FENCE_RE.finditer(item):
                    _append_candidate(candidates, fence_match.group(1))
                    inner_match = JSON_BLOCK_RE.search(fence_match.group(1))
                    if inner_match:
                        _append_candidate(candidates, inner_match.group(0))

    return candidates


def _append_candidate(candidates: list[str], value: str) -> None:
    candidate = value.strip()
    if candidate and candidate not in candidates:
        candidates.append(candidate)


def _try_parse_payload(candidate: str, raw_output: str) -> AgentPayload | None:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict) or "answer" not in parsed:
        return None

    payload = AgentPayload.model_validate(parsed)
    if not payload.answer.strip():
        payload.answer = _fallback_answer(payload)
    payload.metadata.setdefault("raw_output", raw_output)
    return payload


def _try_parse_markdown_table_payload(raw_output: str) -> AgentPayload | None:
    segments = [segment.strip() for segment in raw_output.splitlines() if segment.strip()]
    if len(segments) == 1 and " | " in raw_output:
        segments = _split_inline_markdown_table(raw_output)

    table_lines = [segment for segment in segments if MARKDOWN_TABLE_RE.search(segment)]
    if len(table_lines) < 2:
        return None

    header_index = next((index for index, line in enumerate(table_lines) if _looks_like_markdown_separator_line(line) is False), None)
    if header_index is None or header_index + 1 >= len(table_lines):
        return None

    header_line = table_lines[header_index]
    separator_line = table_lines[header_index + 1]
    if not _looks_like_markdown_separator_line(separator_line):
        return None

    columns = _parse_markdown_table_row(header_line)
    rows: list[list[str]] = []
    for line in table_lines[header_index + 2:]:
        if _looks_like_markdown_separator_line(line):
            continue
        row = _parse_markdown_table_row(line)
        if row:
            rows.append(row)

    if not columns or not rows:
        return None

    answer = raw_output.split("|", 1)[0].strip().rstrip(":")
    if not answer:
        answer = "Here is the requested table."

    return AgentPayload(
        answer=answer + (":" if not answer.endswith(".") and not answer.endswith(":") else ""),
        table=DataTable(title=None, columns=columns, rows=rows),
        metadata={"source": "markdown_table_parser", "raw_output": raw_output},
    )


def _split_inline_markdown_table(raw_output: str) -> list[str]:
    text = re.sub(r"\s+\|", "\n|", raw_output.strip())
    return [segment.strip() for segment in text.splitlines() if segment.strip()]


def _parse_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    if not stripped:
        return []
    return [cell.strip() for cell in stripped.split("|")]


def _looks_like_markdown_separator_line(line: str) -> bool:
    cells = _parse_markdown_table_row(line)
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)

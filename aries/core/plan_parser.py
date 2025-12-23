"""
Plan parsing logic to convert LLM output into structured PlanStep objects.
"""

from __future__ import annotations

import json
import re
from typing import Any

from aries.core.agent_run import PlanStep


def parse_plan(llm_output: str) -> list[PlanStep]:
    """
    Parse LLM output into structured plan steps.
    
    Attempts to parse structured JSON first, then falls back to
    bullet list parsing if JSON parsing fails.
    
    Args:
        llm_output: Raw text output from LLM.
        
    Returns:
        List of PlanStep objects.
    """
    # Try to extract first balanced JSON object
    json_obj = _extract_json_object(llm_output)
    if json_obj:
        try:
            data = json.loads(json_obj)
            if isinstance(data, dict) and "plan" in data:
                steps_data = data["plan"]
                if isinstance(steps_data, list):
                    steps = _parse_json_steps(steps_data)
                    if steps:
                        return steps[:12]  # Clamp to max 12 steps
        except json.JSONDecodeError:
            pass

    # Try to find a JSON array directly
    json_array = _extract_json_array(llm_output)
    if json_array:
        try:
            steps_data = json.loads(json_array)
            if isinstance(steps_data, list):
                steps = _parse_json_steps(steps_data)
                if steps:
                    return steps[:12]  # Clamp to max 12 steps
        except json.JSONDecodeError:
            pass

    # Fallback: parse as bullet list
    steps = _parse_bullet_list(llm_output)
    return steps[:12] if steps else steps  # Clamp to max 12 steps


def _extract_json_object(text: str) -> str | None:
    """Extract first balanced JSON object from text."""
    start = text.find('{')
    if start == -1:
        return None
    
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


def _extract_json_array(text: str) -> str | None:
    """Extract first balanced JSON array from text."""
    start = text.find('[')
    if start == -1:
        return None
    
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


def _parse_json_steps(steps_data: list[dict[str, Any]]) -> list[PlanStep]:
    """Parse steps from JSON structure."""
    steps = []
    for idx, step_data in enumerate(steps_data):
        if not isinstance(step_data, dict):
            continue

        title = step_data.get("title", step_data.get("step", ""))
        if not title:
            continue

        intent = step_data.get("intent", step_data.get("description", ""))
        risk_tier = _extract_risk_tier(step_data.get("risk_tier"), step_data.get("risk"))
        suggested_tools = step_data.get("suggested_tools", step_data.get("tools", []))
        if isinstance(suggested_tools, str):
            suggested_tools = [s.strip() for s in suggested_tools.split(",") if s.strip()]

        inputs_needed = step_data.get("inputs_needed", step_data.get("inputs", []))
        if isinstance(inputs_needed, str):
            inputs_needed = [s.strip() for s in inputs_needed.split(",") if s.strip()]

        success_criteria = step_data.get("success_criteria", step_data.get("success"))

        steps.append(
            PlanStep(
                title=str(title),
                intent=str(intent),
                risk_tier=risk_tier,
                suggested_tools=[str(t) for t in suggested_tools] if isinstance(suggested_tools, list) else [],
                inputs_needed=[str(i) for i in inputs_needed] if isinstance(inputs_needed, list) else [],
                success_criteria=str(success_criteria) if success_criteria else None,
                step_index=idx,
            )
        )

    return steps


def _parse_bullet_list(text: str) -> list[PlanStep]:
    """Fallback parser for bullet list format."""
    steps = []
    lines = text.split("\n")
    step_pattern = re.compile(r'^[-*•]\s*(.+)$', re.MULTILINE)
    numbered_pattern = re.compile(r'^(\d+)\.\s*(.+)$', re.MULTILINE)

    matches = list(step_pattern.finditer(text)) + list(numbered_pattern.finditer(text))
    if not matches:
        # Try to find any lines that look like steps
        for line in lines:
            line = line.strip()
            if line and (line.startswith("-") or line.startswith("*") or line.startswith("•") or re.match(r'^\d+\.', line)):
                title = re.sub(r'^[-*•\d.\s]+', '', line).strip()
                if title:
                    steps.append(
                        PlanStep(
                            title=title,
                            intent=title,
                            risk_tier=0,  # Default to safe tier
                            step_index=len(steps),
                        )
                    )

    else:
        for idx, match in enumerate(matches):
            title = match.group(2) if match.lastindex >= 2 else match.group(1)
            title = title.strip()
            if title:
                steps.append(
                    PlanStep(
                        title=title,
                        intent=title,
                        risk_tier=0,  # Default to safe tier
                        step_index=idx,
                    )
                )

    return steps


def _extract_risk_tier(value: Any, fallback: Any = None) -> int:
    """Extract risk tier from various formats."""
    if value is None:
        value = fallback

    if value is None:
        return 0

    if isinstance(value, int):
        return max(0, min(3, value))

    if isinstance(value, str):
        value_lower = value.lower()
        # Try to parse as number
        try:
            return max(0, min(3, int(value)))
        except ValueError:
            pass

        # Map common risk descriptions
        if "tier 0" in value_lower or "read" in value_lower or "safe" in value_lower:
            return 0
        if "tier 1" in value_lower or "write" in value_lower or "local" in value_lower:
            return 1
        if "tier 2" in value_lower or "desktop" in value_lower or "control" in value_lower:
            return 2
        if "tier 3" in value_lower or "network" in value_lower or "browser" in value_lower or "playwright" in value_lower:
            return 3

    return 0


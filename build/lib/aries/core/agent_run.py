"""
Agent Run domain objects and state management.

Phase B: Agent Runs v1 - stepwise, inspectable agent execution loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from aries.core.cancellation import CancellationToken


class RunStatus(str, Enum):
    """Agent run status states."""

    IDLE = "idle"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"


class StepStatus(str, Enum):
    """Individual step execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class PlanStep:
    """A single step in an agent run plan."""

    title: str
    intent: str
    risk_tier: int  # 0-3
    suggested_tools: list[str] = field(default_factory=list)
    inputs_needed: list[str] = field(default_factory=list)
    success_criteria: str | None = None
    step_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "title": self.title,
            "intent": self.intent,
            "risk_tier": self.risk_tier,
            "suggested_tools": self.suggested_tools,
            "inputs_needed": self.inputs_needed,
            "success_criteria": self.success_criteria,
            "step_index": self.step_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanStep:
        """Create from dictionary."""
        return cls(
            title=data.get("title", ""),
            intent=data.get("intent", ""),
            risk_tier=data.get("risk_tier", 0),
            suggested_tools=data.get("suggested_tools", []),
            inputs_needed=data.get("inputs_needed", []),
            success_criteria=data.get("success_criteria"),
            step_index=data.get("step_index", 0),
        )


@dataclass
class StepResult:
    """Result of executing a single step."""

    step_index: int
    status: StepStatus
    summary: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "step_index": self.step_index,
            "status": self.status.value,
            "summary": self.summary,
            "tool_calls": self.tool_calls,
            "artifacts": self.artifacts,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepResult:
        """Create from dictionary."""
        started_at = None
        completed_at = None
        if data.get("started_at"):
            started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            completed_at = datetime.fromisoformat(data["completed_at"])

        return cls(
            step_index=data.get("step_index", 0),
            status=StepStatus(data.get("status", "pending")),
            summary=data.get("summary", ""),
            tool_calls=data.get("tool_calls", []),
            artifacts=data.get("artifacts", []),
            error=data.get("error"),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=data.get("duration_ms", 0),
        )


@dataclass
class ApprovalDecision:
    """Record of an approval decision for a risk tier."""

    tier: int
    approved: bool
    scope: str  # "once", "session", "denied"
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tier": self.tier,
            "approved": self.approved,
            "scope": self.scope,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalDecision:
        """Create from dictionary."""
        timestamp = datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now()
        return cls(
            tier=data.get("tier", 0),
            approved=data.get("approved", False),
            scope=data.get("scope", "denied"),
            timestamp=timestamp,
        )


@dataclass
class AgentRun:
    """An agent run session with plan, execution state, and history."""

    run_id: str
    goal: str
    status: RunStatus = RunStatus.IDLE
    plan: list[PlanStep] = field(default_factory=list)
    current_step_index: int = 0
    approvals: dict[int, ApprovalDecision] = field(default_factory=dict)  # tier -> decision
    step_results: dict[int, StepResult] = field(default_factory=dict)  # step_index -> result
    started_at: datetime | None = None
    completed_at: datetime | None = None
    model: str = ""
    profile: str = ""
    workspace_name: str | None = None
    cancellation_token: CancellationToken | None = None
    manual_stepping: bool = False
    archived: bool = False
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "status": self.status.value,
            "plan": [step.to_dict() for step in self.plan],
            "current_step_index": self.current_step_index,
            "approvals": {str(k): v.to_dict() for k, v in self.approvals.items()},
            "step_results": [result.to_dict() for result in sorted(self.step_results.values(), key=lambda r: r.step_index)],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "model": self.model,
            "profile": self.profile,
            "workspace_name": self.workspace_name,
            "manual_stepping": getattr(self, "manual_stepping", False),
            "archived": getattr(self, "archived", False),
            "audit_log": getattr(self, "audit_log", []),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRun:
        """Create from dictionary."""
        started_at = None
        completed_at = None
        if data.get("started_at"):
            started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            completed_at = datetime.fromisoformat(data["completed_at"])

        approvals = {}
        if "approvals" in data:
            for k, v in data["approvals"].items():
                approvals[int(k)] = ApprovalDecision.from_dict(v)

        return cls(
            run_id=data.get("run_id", ""),
            goal=data.get("goal", ""),
            status=RunStatus(data.get("status", "idle")),
            plan=[PlanStep.from_dict(s) for s in data.get("plan", [])],
            current_step_index=data.get("current_step_index", 0),
            approvals=approvals,
            step_results={r.step_index: r for r in [StepResult.from_dict(r) for r in data.get("step_results", [])]},
            started_at=started_at,
            completed_at=completed_at,
            model=data.get("model", ""),
            profile=data.get("profile", ""),
            workspace_name=data.get("workspace_name"),
        )
        # Set optional attributes
        run.manual_stepping = data.get("manual_stepping", False)
        run.archived = data.get("archived", False)
        run.audit_log = data.get("audit_log", [])
        return run

    def get_current_step(self) -> PlanStep | None:
        """Get the current step being executed."""
        if 0 <= self.current_step_index < len(self.plan):
            return self.plan[self.current_step_index]
        return None

    def get_step_result(self, step_index: int) -> StepResult | None:
        """Get result for a specific step."""
        return self.step_results.get(step_index)

    def set_step_result(self, result: StepResult) -> None:
        """Set result for a step."""
        self.step_results[result.step_index] = result

    def is_approved_for_tier(self, tier: int) -> bool:
        """Check if a risk tier is approved for this run."""
        if tier == 0:
            # Tier 0 is always allowed
            return True

        decision = self.approvals.get(tier)
        if not decision:
            return False

        if decision.scope == "denied":
            return False

        if decision.scope == "once":
            # "once" approvals are consumed after first use
            return decision.approved

        if decision.scope == "session":
            return decision.approved

        return False

    def consume_once_approval(self, tier: int) -> None:
        """Consume a 'once' approval after use."""
        decision = self.approvals.get(tier)
        if decision and decision.scope == "once" and decision.approved:
            decision.scope = "denied"

    def duration_seconds(self) -> float | None:
        """Calculate run duration in seconds."""
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()


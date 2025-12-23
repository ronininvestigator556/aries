"""
Tests for Agent Run functionality (Phase B).
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from aries.core.agent_run import (
    AgentRun,
    ApprovalDecision,
    PlanStep,
    RunStatus,
    StepResult,
    StepStatus,
)
from aries.core.cancellation import CancellationToken
from aries.core.plan_parser import parse_plan
from aries.core.run_manager import RunManager


def test_plan_step_serialization():
    """Test PlanStep serialization and deserialization."""
    step = PlanStep(
        title="Test step",
        intent="Test intent",
        risk_tier=2,
        suggested_tools=["read_file", "write_file"],
        inputs_needed=["config_path"],
        success_criteria="File written successfully",
        step_index=0,
    )

    data = step.to_dict()
    assert data["title"] == "Test step"
    assert data["risk_tier"] == 2

    restored = PlanStep.from_dict(data)
    assert restored.title == step.title
    assert restored.risk_tier == step.risk_tier
    assert restored.suggested_tools == step.suggested_tools


def test_step_result_serialization():
    """Test StepResult serialization."""
    result = StepResult(
        step_index=0,
        status=StepStatus.COMPLETED,
        summary="Step completed",
        tool_calls=[{"tool_id": "read_file", "args_hash": "abc123"}],
        artifacts=[{"id": "artifact1", "path": "/path/to/file"}],
        started_at=datetime.now(),
        completed_at=datetime.now(),
        duration_ms=100,
    )

    data = result.to_dict()
    assert data["status"] == "completed"
    assert data["step_index"] == 0

    restored = StepResult.from_dict(data)
    assert restored.status == StepStatus.COMPLETED
    assert restored.summary == result.summary


def test_agent_run_serialization():
    """Test AgentRun serialization."""
    run = AgentRun(
        run_id="test_run_123",
        goal="Test goal",
        status=RunStatus.RUNNING,
        plan=[
            PlanStep(title="Step 1", intent="Do something", risk_tier=0, step_index=0),
        ],
        current_step_index=0,
        model="llama3.2",
        profile="default",
        workspace_name="test_workspace",
    )
    run.started_at = datetime.now()

    data = run.to_dict()
    assert data["run_id"] == "test_run_123"
    assert data["status"] == "running"
    assert len(data["plan"]) == 1

    restored = AgentRun.from_dict(data)
    assert restored.run_id == run.run_id
    assert restored.status == RunStatus.RUNNING
    assert len(restored.plan) == 1


def test_plan_parsing_json():
    """Test parsing structured JSON plan."""
    json_plan = """
    {
      "plan": [
        {
          "title": "Read config",
          "intent": "Load configuration file",
          "risk_tier": 0,
          "suggested_tools": ["read_file"],
          "inputs_needed": [],
          "success_criteria": "Config loaded"
        },
        {
          "title": "Process data",
          "intent": "Transform data",
          "risk_tier": 1,
          "suggested_tools": ["write_file"],
          "success_criteria": "Data processed"
        }
      ]
    }
    """

    steps = parse_plan(json_plan)
    assert len(steps) == 2
    assert steps[0].title == "Read config"
    assert steps[0].risk_tier == 0
    assert steps[1].risk_tier == 1
    assert "read_file" in steps[0].suggested_tools


def test_plan_parsing_bullet_list():
    """Test parsing fallback bullet list."""
    bullet_plan = """
    - Step 1: Read configuration
    - Step 2: Process data
    - Step 3: Write results
    """

    steps = parse_plan(bullet_plan)
    assert len(steps) >= 3
    assert "Read configuration" in steps[0].title
    assert steps[0].risk_tier == 0  # Default tier


def test_plan_parsing_malformed():
    """Test parsing handles malformed input gracefully."""
    malformed = "This is not a plan at all, just some text."

    steps = parse_plan(malformed)
    # Should return empty list or fallback
    assert isinstance(steps, list)


def test_approval_decisions():
    """Test approval decision tracking."""
    run = AgentRun(
        run_id="test",
        goal="Test",
        status=RunStatus.RUNNING,
    )

    # Tier 0 is always allowed
    assert run.is_approved_for_tier(0) is True
    
    # Tier 1 requires approval (not auto-approved)
    assert run.is_approved_for_tier(1) is False

    # Tier 2+ requires approval
    assert run.is_approved_for_tier(2) is False

    # Add approval
    decision = ApprovalDecision(tier=2, approved=True, scope="session")
    run.approvals[2] = decision
    assert run.is_approved_for_tier(2) is True

    # Denied approval
    decision_denied = ApprovalDecision(tier=3, approved=False, scope="denied")
    run.approvals[3] = decision_denied
    assert run.is_approved_for_tier(3) is False


def test_run_status_transitions():
    """Test run status state machine."""
    run = AgentRun(
        run_id="test",
        goal="Test",
        status=RunStatus.IDLE,
    )

    assert run.status == RunStatus.IDLE

    run.status = RunStatus.PLANNING
    assert run.status == RunStatus.PLANNING

    run.status = RunStatus.RUNNING
    assert run.status == RunStatus.RUNNING

    run.status = RunStatus.PAUSED
    assert run.status == RunStatus.PAUSED

    run.status = RunStatus.COMPLETED
    assert run.status == RunStatus.COMPLETED


def test_run_manager_persistence(tmp_path: Path):
    """Test run manager save/load functionality."""
    runs_dir = tmp_path / "runs"
    manager = RunManager(workspace_root=tmp_path)

    run = AgentRun(
        run_id="test_persistence",
        goal="Test persistence",
        status=RunStatus.RUNNING,
        model="llama3.2",
        profile="default",
    )
    run.started_at = datetime.now()

    manager.save_run(run)
    assert (runs_dir / "test_persistence.json").exists()

    loaded = manager.load_run("test_persistence")
    assert loaded is not None
    assert loaded.run_id == run.run_id
    assert loaded.goal == run.goal
    assert loaded.status == RunStatus.RUNNING


def test_run_report_generation(tmp_path: Path):
    """Test run report generation."""
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    manager = RunManager(workspace_root=tmp_path)

    run = AgentRun(
        run_id="test_report",
        goal="Test report generation",
        status=RunStatus.COMPLETED,
        plan=[
            PlanStep(title="Step 1", intent="Do something", risk_tier=0, step_index=0),
        ],
        model="llama3.2",
        profile="default",
        workspace_name="test",
    )
    run.started_at = datetime.now()
    run.completed_at = datetime.now()

    result = StepResult(
        step_index=0,
        status=StepStatus.COMPLETED,
        summary="Step completed successfully",
        tool_calls=[{"tool_id": "read_file", "args_hash": "abc123"}],
        artifacts=[{"id": "artifact1"}],
    )
    result.started_at = datetime.now()
    result.completed_at = datetime.now()
    result.duration_ms = 100

    run.set_step_result(result)

    markdown, json_data = manager.generate_run_report(run, artifact_dir)

    assert "Agent Run Report" in markdown
    assert "test_report" in markdown
    assert "Test report generation" in markdown
    assert "Step 1" in markdown

    assert json_data["run_id"] == "test_report"
    assert json_data["status"] == "completed"
    assert len(json_data["step_results"]) == 1


def test_run_duration_calculation():
    """Test run duration calculation."""
    run = AgentRun(
        run_id="test",
        goal="Test",
        status=RunStatus.COMPLETED,
    )

    run.started_at = datetime(2024, 1, 1, 10, 0, 0)
    run.completed_at = datetime(2024, 1, 1, 10, 0, 30)

    duration = run.duration_seconds()
    assert duration == 30.0

    # Test without completion time
    run.completed_at = None
    duration = run.duration_seconds()
    assert duration is not None  # Should calculate from now


def test_cancellation_token():
    """Test cancellation token functionality."""
    token = CancellationToken()
    assert token.is_cancelled is False

    token.cancel()
    assert token.is_cancelled is True


def test_get_current_step():
    """Test getting current step from run."""
    run = AgentRun(
        run_id="test",
        goal="Test",
        status=RunStatus.RUNNING,
        plan=[
            PlanStep(title="Step 1", intent="Do something", risk_tier=0, step_index=0),
            PlanStep(title="Step 2", intent="Do more", risk_tier=1, step_index=1),
        ],
        current_step_index=1,
    )

    current = run.get_current_step()
    assert current is not None
    assert current.title == "Step 2"

    run.current_step_index = 0
    current = run.get_current_step()
    assert current.title == "Step 1"


def test_get_step_result():
    """Test getting step result from run."""
    run = AgentRun(
        run_id="test",
        goal="Test",
        status=RunStatus.RUNNING,
        plan=[
            PlanStep(title="Step 1", intent="Do something", risk_tier=0, step_index=0),
        ],
    )

    result = StepResult(
        step_index=0,
        status=StepStatus.COMPLETED,
        summary="Done",
    )

    run.set_step_result(result)

    retrieved = run.get_step_result(0)
    assert retrieved is not None
    assert retrieved.summary == "Done"

    assert run.get_step_result(999) is None


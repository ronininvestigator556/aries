from __future__ import annotations

from dataclasses import dataclass

import pytest

from aries.config import Config
from aries.core.desktop_ops import DesktopOpsController, DesktopRisk
from aries.tools.base import BaseTool, ToolResult


@dataclass
class DummyTool(BaseTool):
    name: str = "dummy"
    description: str = "dummy"
    risk_level: str = "read"
    requires_shell: bool = False

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"command": {"type": "string"}}, "required": []}

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content="ok")


@pytest.mark.parametrize("mode", ["guide", "commander", "strict"])
@pytest.mark.parametrize(
    "risk",
    [
        DesktopRisk.READ_ONLY,
        DesktopRisk.WRITE_SAFE,
        DesktopRisk.WRITE_DESTRUCTIVE,
        DesktopRisk.EXEC_USERSPACE,
        DesktopRisk.EXEC_PRIVILEGED,
        DesktopRisk.NETWORK,
    ],
)
@pytest.mark.parametrize("allowlisted", [False, True])
def test_policy_matrix(mode: str, risk: DesktopRisk, allowlisted: bool) -> None:
    config = Config()
    controller = DesktopOpsController(type("App", (), {"config": config, "workspace": None})(), mode=mode)
    tool = DummyTool()
    args = {"command": "echo ok"}
    controller.config.auto_exec_allowlist = ["dummy:echo ok"] if allowlisted else []

    if mode == "strict":
        expected = True
    elif mode == "commander":
        if risk == DesktopRisk.READ_ONLY:
            expected = False
        elif risk == DesktopRisk.EXEC_USERSPACE and allowlisted:
            expected = False
        elif risk in {DesktopRisk.WRITE_SAFE}:
            expected = False
        elif allowlisted and risk in {DesktopRisk.WRITE_DESTRUCTIVE, DesktopRisk.EXEC_PRIVILEGED, DesktopRisk.NETWORK}:
            expected = False
        else:
            expected = True
    else:  # guide
        if risk == DesktopRisk.READ_ONLY:
            expected = False
        elif risk == DesktopRisk.EXEC_USERSPACE and allowlisted:
            expected = False
        elif allowlisted and risk in {DesktopRisk.WRITE_DESTRUCTIVE, DesktopRisk.EXEC_PRIVILEGED, DesktopRisk.NETWORK}:
            expected = False
        else:
            expected = True

    assert controller._requires_approval(risk, tool, args) is expected

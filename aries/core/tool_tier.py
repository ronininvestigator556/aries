"""
Tool risk tier mapping - maps tool risk levels to agent run tiers.
"""

from typing import Any

from aries.tools.base import BaseTool


def tool_to_tier(tool: BaseTool, workspace_root: Any = None) -> int:
    """
    Map a tool's risk characteristics to an agent run tier.
    
    Tiers:
    - 0: read-only, local processing, RAG retrieval
    - 1: local writes/artifact creation (workspace-scoped)
    - 2: Desktop Commander actions (desktop control), shell execution
    - 3: Playwright or any networked/browser automation
    
    Args:
        tool: The tool to evaluate.
        workspace_root: Optional workspace root to check if writes are workspace-scoped.
        
    Returns:
        Risk tier (0-3).
    """
    risk_level = getattr(tool, "risk_level", "read").lower()
    requires_network = getattr(tool, "requires_network", False)
    requires_shell = getattr(tool, "requires_shell", False)
    mutates_state = getattr(tool, "mutates_state", False)
    provider_id = getattr(tool, "provider_id", "")
    provider_key = getattr(tool, "provider_key", "")
    server_id = getattr(tool, "server_id", "")

    # Tier 3: Network/browser automation
    if requires_network or provider_id in ("mcp_playwright", "playwright"):
        return 3

    # Tier 2: Desktop control, shell execution, or non-workspace writes
    if (
        requires_shell
        or provider_id in ("mcp_desktop_commander", "desktop_commander")
        or provider_key.startswith("mcp:desktop")
        or server_id in ("desktop_commander", "desktop")
    ):
        return 2

    # Tier 1: Local writes (workspace-scoped)
    if risk_level == "write" and mutates_state:
        # Check if writes are workspace-scoped (simplified: assume workspace tools are Tier 1)
        if workspace_root and hasattr(tool, "path_params"):
            # If tool has path_params, it likely respects workspace boundaries
            return 1
        # Non-workspace writes are Tier 2
        return 2

    # Tier 0: Read-only
    if risk_level == "read":
        return 0

    # Default: exec without network/shell is Tier 2
    if risk_level == "exec":
        return 2

    # Fallback to Tier 0 for unknown
    return 0


def effective_tier(step_tier: int, tool_tier: int) -> int:
    """
    Calculate effective tier as max of step tier and tool tier.
    
    This ensures that tool-level risk always takes precedence.
    
    Args:
        step_tier: The tier assigned to the plan step.
        tool_tier: The tier of the tool being called.
        
    Returns:
        Effective tier (max of both).
    """
    return max(step_tier, tool_tier)

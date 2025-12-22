"""
/profile command - manage prompt profiles.
"""

from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.ui.display import display_error, display_info, display_success

if TYPE_CHECKING:
    from aries.cli import Aries


class ProfileCommand(BaseCommand):
    """List, show, or use prompt profiles."""

    name = "profile"
    description = "Manage prompt profiles"
    usage = "list|show <name>|use <name>"

    async def execute(self, app: "Aries", args: str) -> None:
        args = args.strip()
        if not args or args == "list":
            names = app.profiles.list()
            if not names:
                display_info("No profiles found.")
                return
            display_info("Profiles:")
            active = app.current_prompt
            for name in names:
                marker = " (active)" if active == name else ""
                display_info(f"- {name}{marker}")
            return

        if args.startswith("show "):
            name = args.split(maxsplit=1)[1]
            try:
                summary = app.profiles.describe(name)
            except FileNotFoundError as exc:
                display_error(str(exc))
                return
            display_info(summary)
            return

        if args.startswith("use "):
            name = args.split(maxsplit=1)[1]
            try:
                profile = app.profiles.load(name)
            except FileNotFoundError as exc:
                display_error(str(exc))
                return
            if profile.system_prompt:
                app.conversation.set_system_prompt(profile.system_prompt)
            if profile.tool_policy:
                app.tool_policy.config.allow_shell = profile.tool_policy.get("allow_shell", False)
                app.tool_policy.config.allow_network = profile.tool_policy.get("allow_network", False)
            app.current_prompt = name
            display_success(f"Profile '{name}' activated.")
            return

        display_error(f"Unknown profile command: {args}")

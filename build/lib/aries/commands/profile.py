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
                profile = app._load_profile(
                    name,
                    allow_legacy_prompt=not app.config.profiles.require,
                    require_profile=app.config.profiles.require,
                )
            except Exception as exc:
                display_error(str(exc))
                return
            app._apply_profile(profile)
            display_success(f"Profile '{name}' activated.")
            return

        display_error(f"Unknown profile command: {args}")

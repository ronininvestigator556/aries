"""
Entry point for running Aries as a module.

Usage:
    python -m aries
    python -m aries --help
    python -m aries index /path/to/docs --name my_index
"""

import asyncio
import sys

from aries.cli import run_cli


def main() -> int:
    """Main entry point."""
    try:
        return asyncio.run(run_cli())
    except KeyboardInterrupt:
        print("\nGoodbye!")
        return 0
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

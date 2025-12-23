import types

import pytest

from aries import cli


def test_main_callable_exists() -> None:
    assert hasattr(cli, "main")
    assert callable(cli.main)


def test_version_guard_accepts_supported_version() -> None:
    supported = types.SimpleNamespace(major=3, minor=11, micro=0)
    cli._ensure_supported_python(supported)


def test_version_guard_rejects_unsupported_version() -> None:
    unsupported = types.SimpleNamespace(major=3, minor=14, micro=0)
    with pytest.raises(RuntimeError):
        cli._ensure_supported_python(unsupported)

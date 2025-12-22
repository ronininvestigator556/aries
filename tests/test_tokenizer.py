import sys

import pytest

from aries.core import tokenizer as tokenizer_module


def test_tiktoken_failure_falls_back_to_approx(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    class _BrokenTiktoken:
        @staticmethod
        def get_encoding(_: str) -> None:
            raise RuntimeError("no encoding download")

    monkeypatch.setitem(sys.modules, "tiktoken", _BrokenTiktoken())
    caplog.set_level("WARNING", logger="aries.core.tokenizer")

    estimator = tokenizer_module.TokenEstimator(mode="tiktoken", encoding="missing")

    assert estimator.mode == "approx"
    assert estimator.count("text to measure") > 0
    assert any("tiktoken" in rec.message for rec in caplog.records)


def test_disabled_mode_short_circuits_counts() -> None:
    estimator = tokenizer_module.TokenEstimator(mode="disabled")

    assert estimator.is_disabled is True
    assert estimator.count("anything") == 0
    assert estimator.encode("anything") == ["anything"]

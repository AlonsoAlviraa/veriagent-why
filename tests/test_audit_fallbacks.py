"""Audit fixes: Zetaris is the default when configured, SAMPLE_MODE is an explicit, announced fallback;
Meterless fallback is loud and can be made fatal; test artefacts stay out of logs/."""
import pytest
from app import config


def test_sample_mode_default_follows_zetaris_config(monkeypatch):
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    monkeypatch.delenv("ZETARIS_BACKEND", raising=False)
    monkeypatch.delenv("ZETARIS_JDBC_URL", raising=False)
    assert config.sample_mode() is True and "fallback" in config.sample_mode_reason()
    monkeypatch.setenv("ZETARIS_BACKEND", "zetaris")
    assert config.sample_mode() is False
    monkeypatch.setenv("SAMPLE_MODE", "true")
    assert config.sample_mode() is True


def test_sample_run_is_labelled(capsys):
    from app.pipeline import run
    r = run({"query": "Why did on-time delivery drop between 2026-10-01 and 2026-10-14 compared with 2026-09-15 to 2026-09-30?",
             "kpi": "on_time_rate", "baseline": ["2026-09-15", "2026-09-30"], "period": ["2026-10-01", "2026-10-14"]}, "t-audit-label")
    o = r["output"]["result"]
    assert o["backends"]["data"].startswith("sample")
    assert "SAMPLE MODE: no Zetaris" in o["memo_md"] and "SYNTHETIC" in o["memo_md"]
    assert "SAMPLE MODE" in capsys.readouterr().err
    assert not (config.ROOT / "logs" / "trace-t-audit-label.jsonl").exists()


def test_meterless_required_fails_loudly(monkeypatch):
    from app import pipeline
    monkeypatch.setenv("METERLESS_REQUIRED", "1")
    def boom():
        raise RuntimeError("node missing")
    monkeypatch.setattr(pipeline, "Bridge", boom)
    with pytest.raises(RuntimeError, match="METERLESS_REQUIRED"):
        pipeline.run({"query": "Why did on-time delivery drop?", "kpi": "on_time_rate",
                      "baseline": ["2026-09-15", "2026-09-30"], "period": ["2026-10-01", "2026-10-14"]}, "t-audit-mreq")


def test_meterless_fallback_is_visible(monkeypatch, capsys):
    from app import pipeline
    monkeypatch.delenv("METERLESS_REQUIRED", raising=False)
    def boom():
        raise RuntimeError("node missing")
    monkeypatch.setattr(pipeline, "Bridge", boom)
    r = pipeline.run({"query": "Why did on-time delivery drop?", "kpi": "on_time_rate",
                      "baseline": ["2026-09-15", "2026-09-30"], "period": ["2026-10-01", "2026-10-14"]}, "t-audit-mfb")
    assert "NOT Meterless" in r["output"]["result"]["backends"]["meterless"]
    assert "NOT Meterless" in r["output"]["result"]["memo_md"]
    assert "NOT Meterless" in capsys.readouterr().err

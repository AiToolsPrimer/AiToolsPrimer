from pathlib import Path

import pytest

from agency.llm.hosted import HostedLLM
from agency.models import registry
from agency.models.host import HostError, ModelHost


class CountingHost(ModelHost):
    """Dry-run host that records starts/stops so swaps can be asserted."""

    def __init__(self, **kw):
        super().__init__(dry_run=True, **kw)
        self.starts: list[str] = []
        self.stops: list[str] = []

    def _start(self, spec):
        self.starts.append(spec.name)
        return super()._start(spec)

    def _stop(self, backend):
        self.stops.append(backend.spec.name)
        super()._stop(backend)


def test_one_model_at_a_time_swaps_and_dedupes():
    h = CountingHost()
    brain, second = registry.resolve("brain"), registry.resolve("second_writer")
    h.activate(brain)
    h.activate(brain)            # no second start
    h.activate(second)           # swaps
    h.activate(brain)
    assert h.starts == [brain.name, second.name, brain.name]
    assert h.stops == [brain.name, second.name]
    assert h.resident().name == brain.name


def test_media_job_releases_resident_model(tmp_path: Path):
    h = CountingHost()
    h.activate(registry.resolve("brain"))
    out = h.run_job(registry.resolve("tts"), registry.resolve("tts").command, {"text": "a.txt", "out": "a.wav", "voice": "default"})
    assert out.startswith("[dry-run]") and "tts_stepaudio.py" in out
    assert h.resident() is None
    assert any(e["kind"] == "job.done" for e in h.history)


def test_benchmark_dry_run_and_brain_choice(tmp_path: Path):
    from agency.models.host import BrainChoice

    h = ModelHost(dry_run=True)
    r = h.benchmark(registry.resolve("brain"))
    assert r["ok"] and r["dry_run"]
    bc = BrainChoice(tmp_path / "brain.json")
    assert bc.chosen_name() is None
    bc.save({"brain": "Qwen3.8-27B (8-bit)"})
    assert bc.chosen_name() == "Qwen3.8-27B (8-bit)"


def test_hosted_llm_fails_over_to_the_27b(monkeypatch):
    h = ModelHost(dry_run=True)
    events = []
    h.on_event = events.append
    brain, fallback = registry.candidates("brain")[:2]
    llm = HostedLLM(h, brain, fallback=fallback)

    class Boom:
        def __init__(self, fail):
            self.fail = fail
            self.base_url = "http://dry-run"

        def chat(self, *a, **k):
            if self.fail:
                raise RuntimeError("server down")
            return "ok"

    calls = {"n": 0}

    def fake_client_for(spec):
        calls["n"] += 1
        llm._client_spec = spec
        return Boom(fail=spec.id == brain.id)

    monkeypatch.setattr(llm, "_client_for", fake_client_for)
    assert llm.chat([]) == "ok"
    assert llm.failed_over and llm.model.id == fallback.id
    assert any(e.get("kind") == "brain.failover" for e in events)


def test_agency_benchmark_picks_strongest_that_runs(agency):
    out = agency.benchmark_brains()
    assert out["chosen"] == "Qwen3.8-Flash-Next"          # dry run: everything "runs"
    assert agency.brain_choice.chosen_name() == "Qwen3.8-Flash-Next"
    assert agency.status()["brain"] == "Qwen3.8-Flash-Next"


def test_missing_runtime_is_a_clear_error(tmp_path):
    h = ModelHost(dry_run=False, lms_cli="definitely-not-installed-lms", state_dir=tmp_path)
    with pytest.raises(HostError):
        h.activate(registry.resolve("second_writer"))

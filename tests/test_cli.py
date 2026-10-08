"""Tests for the CLI: flags, exit codes, dry-run output, loop control."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from dump1090_to_mqtt.cli import main
from dump1090_to_mqtt.client import RecordingClient
from dump1090_to_mqtt.config import Settings
from dump1090_to_mqtt.fetch import FetchError
from dump1090_to_mqtt.publisher import MqttPublisher
from fakes import FakeClient


class FetchStub:
    """Stands in for ``fetch_aircraft``: records calls, never touches HTTP."""

    def __init__(
        self,
        aircraft: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.aircraft = aircraft or []
        self.error = error
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout: float = 0.0) -> list[dict[str, Any]]:
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return [dict(entry) for entry in self.aircraft]


def run(
    argv: list[str],
    *,
    fetch: FetchStub | None = None,
    publisher: MqttPublisher | None = None,
    sleep: Any = lambda _delay: None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(
        argv,
        fetch=fetch if fetch is not None else FetchStub(),
        publisher=publisher,
        sleep=sleep,
        env={} if env is None else env,
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# basics
# ---------------------------------------------------------------------------


def test_version_flag_prints_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "dump1090-to-mqtt 0.1.0" in capsys.readouterr().out


def test_config_error_exits_nonzero_without_touching_the_broker() -> None:
    client = FakeClient()
    publisher = MqttPublisher(Settings(), client=client)
    code, _, err = run(["--once"], publisher=publisher, env={"MQTT_PORT": "not-a-port"})
    assert code == 1
    assert "error: MQTT_PORT" in err
    assert client.events == []


def test_header_reports_source_and_target() -> None:
    code, _, err = run(["--dry-run", "--once"], env={"MQTT_HOST": "broker.lan"})
    assert code == 0
    assert "http://localhost:8080 -> dry-run, no MQTT connection" in err
    assert "every 2.0s" in err


def test_header_shows_mqtt_target_when_not_dry_run() -> None:
    publisher = MqttPublisher(Settings(), client=FakeClient())
    code, _, err = run(["--once"], publisher=publisher, env={"MQTT_TOPIC_PREFIX": "adsb"})
    assert code == 0
    assert "mqtt://localhost:1883, prefix adsb" in err


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_dry_run_once_prints_every_topic_and_payload() -> None:
    fetch = FetchStub(aircraft=[{"hex": "abc123", "alt_baro": 12000, "gs": 300}])
    code, out, err = run(["--dry-run", "--once"], fetch=fetch)
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("dump1090/status online")
    topics = [line.split(" ", 1)[0] for line in lines]
    assert "dump1090/aircraft/abc123" in topics
    assert "dump1090/aircraft/abc123/attributes" in topics
    assert "dump1090/count" in topics
    assert "homeassistant/sensor/dump1090_abc123_altitude/config" in topics
    assert "homeassistant/sensor/dump1090_abc123_squawk/config" in topics
    state_line = next(line for line in lines if line.startswith("dump1090/aircraft/abc123 "))
    state = json.loads(state_line.split(" ", 1)[1])
    assert state["hex"] == "abc123"
    attrs_line = next(
        line for line in lines if line.startswith("dump1090/aircraft/abc123/attributes ")
    )
    attrs = json.loads(attrs_line.split(" ", 1)[1])
    assert attrs["altitude"] == 12000
    assert "dry-run" in err


def test_dry_run_republishes_count_but_not_status_each_poll() -> None:
    fetch = FetchStub(aircraft=[])
    code, out, _ = run(["--dry-run", "--max-polls", "2"], fetch=fetch)
    assert code == 0
    lines = out.splitlines()
    assert sum(1 for line in lines if line.startswith("dump1090/status ")) == 1
    assert sum(1 for line in lines if line.startswith("dump1090/count ")) == 2


def test_dry_run_fetch_failure_exits_nonzero() -> None:
    fetch = FetchStub(error=FetchError("cannot read http://localhost:8080/data/aircraft.json"))
    code, _, err = run(["--dry-run", "--once"], fetch=fetch)
    assert code == 1
    assert "error: cannot read" in err


# ---------------------------------------------------------------------------
# live loop (injected publisher, fake client — no broker)
# ---------------------------------------------------------------------------


def test_run_once_connects_polls_publishes_and_stops() -> None:
    client = FakeClient()
    publisher = MqttPublisher(Settings(), client=client, sleep=lambda _delay: None)
    fetch = FetchStub(aircraft=[{"hex": "abc123", "alt_baro": 9000}])
    code, _, err = run(["--once"], fetch=fetch, publisher=publisher)
    assert code == 0
    assert client.connect_calls == [("localhost", 1883, 60)]
    assert client.wills == [("dump1090/status", "offline", 1, True)]
    assert client.payloads("dump1090/status") == ["online", "offline"]
    assert client.payloads("dump1090/aircraft/abc123") == [
        json.dumps({"hex": "abc123", "alt_baro": 9000})
    ]
    assert client.disconnect_count == 1
    assert client.loop_stops == 1
    assert "mqtt://localhost:1883" in err


def test_broker_start_failure_exits_nonzero() -> None:
    client = FakeClient(connect_error=OSError("connection refused"))
    publisher = MqttPublisher(Settings(), client=client, sleep=lambda _delay: None)
    code, _, err = run(["--once"], publisher=publisher)
    assert code == 1
    assert "error: cannot connect to MQTT broker localhost:1883" in err
    assert client.loop_starts == 0


def test_max_polls_limits_fetches_and_sleeps_between_them() -> None:
    sleeps: list[float] = []
    fetch = FetchStub(aircraft=[])
    code, _, _ = run(["--dry-run", "--max-polls", "3"], fetch=fetch, sleep=sleeps.append)
    assert code == 0
    assert len(fetch.calls) == 3
    assert sleeps == [2.0, 2.0]


def test_interval_comes_from_environment() -> None:
    sleeps: list[float] = []
    fetch = FetchStub(aircraft=[])
    run(
        ["--dry-run", "--max-polls", "3"],
        fetch=fetch,
        sleep=sleeps.append,
        env={"DUMP1090_INTERVAL": "0.25"},
    )
    assert sleeps == [0.25, 0.25]


def test_fetch_receives_configured_url_and_timeout() -> None:
    fetch = FetchStub(aircraft=[])
    run(["--dry-run", "--once"], fetch=fetch, env={"DUMP1090_URL": "http://decoder:8080"})
    # fetch_aircraft itself resolves the base URL to /data/aircraft.json
    # (see tests/test_fetch.py); the CLI forwards the configured value.
    assert fetch.calls == [("http://decoder:8080", 5.0)]

    fetch2 = FetchStub(aircraft=[])
    run(
        ["--dry-run", "--once", "--timeout", "1.5"],
        fetch=fetch2,
        env={"DUMP1090_URL": "http://decoder:8080/data/aircraft.json"},
    )
    assert fetch2.calls == [("http://decoder:8080/data/aircraft.json", 1.5)]


def test_repeated_fetch_failures_do_not_abort_the_loop() -> None:
    sleeps: list[float] = []
    fetch = FetchStub(error=FetchError("boom"))
    code, _, err = run(["--dry-run", "--max-polls", "2"], fetch=fetch, sleep=sleeps.append)
    assert code == 0
    assert len(fetch.calls) == 2
    assert sleeps == [2.0]
    assert err.count("error: boom") == 2


def test_keyboard_interrupt_stops_gracefully() -> None:
    def raise_interrupt(_delay: float) -> None:
        raise KeyboardInterrupt

    fetch = FetchStub(aircraft=[{"hex": "abc123"}])
    code, _, err = run(["--dry-run"], fetch=fetch, sleep=raise_interrupt)
    assert code == 0
    assert "# stopped" in err


def test_once_flag_means_single_poll_without_sleeping() -> None:
    sleeps: list[float] = []
    fetch = FetchStub(aircraft=[])
    code, _, _ = run(["--dry-run", "--once"], fetch=fetch, sleep=sleeps.append)
    assert code == 0
    assert len(fetch.calls) == 1
    assert sleeps == []


# ---------------------------------------------------------------------------
# RecordingClient (the --dry-run transport)
# ---------------------------------------------------------------------------


def test_recording_client_records_lifecycle_and_messages() -> None:
    rec = RecordingClient()
    rec.will_set("dump1090/status", "offline", qos=1, retain=True)
    rec.username_pw_set("user", "pass")
    rec.tls_set(ca_certs="ca.pem")
    rec.tls_insecure_set(True)
    assert rec.connect("broker", 8883, 60) == 0
    assert rec.is_connected() is True
    assert rec.reconnect() == 0
    assert rec.loop_start() == 0
    assert rec.looping is True
    assert rec.loop_stop() == 0
    assert rec.looping is False
    rec.publish("t1", "payload", qos=1, retain=True)
    rec.publish("t2", None)
    assert rec.drain() == [("t1", "payload"), ("t2", "")]
    assert rec.drain() == []
    assert rec.disconnect() == 0
    assert rec.disconnects == 1
    assert rec.is_connected() is False
    assert rec.wills == [("dump1090/status", "offline", 1, True)]
    assert rec.credentials == ("user", "pass")
    assert rec.tls_calls == ["ca.pem"]
    assert rec.tls_insecure is True
    assert rec.connect_calls == [("broker", 8883, 60)]

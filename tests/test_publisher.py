"""Tests for the MQTT publisher: payloads, topics, status/LWT, backoff, retire."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from paho.mqtt.enums import CallbackAPIVersion

from dump1090_to_mqtt.config import Settings
from dump1090_to_mqtt.publisher import OFFLINE, ONLINE, MqttPublisher
from fakes import FakeClient, Harness


def plane(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "hex": "abc123",
        "flight": "BAW117  ",
        "alt_baro": 34000,
        "gs": 420,
        "track": 90.0,
        "squawk": "1200",
        "rssi": -4.3,
    }
    base.update(fields)
    return base


# ---------------------------------------------------------------------------
# start / birth / LWT
# ---------------------------------------------------------------------------


def test_start_registers_lwt_before_connecting() -> None:
    h = Harness()
    h.publisher.start()
    assert h.client.events.index("will_set") < h.client.events.index("connect")
    assert h.client.wills == [("dump1090/status", OFFLINE, 1, True)]
    assert h.client.connect_calls == [("localhost", 1883, 60)]
    assert h.client.loop_starts == 1


def test_start_connects_to_configured_broker() -> None:
    h = Harness(Settings(mqtt_host="broker.lan", mqtt_port=8883))
    h.publisher.start()
    assert h.client.connect_calls == [("broker.lan", 8883, 60)]


def test_start_applies_credentials_when_configured() -> None:
    h = Harness(Settings(mqtt_username="bridge", mqtt_password="s3cret"))
    h.publisher.start()
    assert h.client.credentials == ("bridge", "s3cret")


def test_start_skips_credentials_when_absent() -> None:
    h = Harness()
    h.publisher.start()
    assert h.client.credentials is None


def test_start_configures_tls_with_ca_and_insecure_flag() -> None:
    h = Harness(Settings(tls=True, tls_ca="/etc/ca.pem", tls_insecure=True))
    h.publisher.start()
    assert h.client.tls_calls == ["/etc/ca.pem"]
    assert h.client.tls_insecure_flags == [True]


def test_start_tls_without_ca_uses_system_roots() -> None:
    h = Harness(Settings(tls=True))
    h.publisher.start()
    assert h.client.tls_calls == [None]
    assert h.client.tls_insecure_flags == []


def test_start_wraps_connection_failure() -> None:
    h = Harness(connect_error=OSError("connection refused"))
    with pytest.raises(ConnectionError, match="cannot connect to MQTT broker localhost:1883"):
        h.publisher.start()
    assert h.client.loop_starts == 0


# ---------------------------------------------------------------------------
# poll publishing
# ---------------------------------------------------------------------------


def test_first_poll_publishes_birth_then_full_state() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane()])
    published = h.client.published
    assert published[0].topic == "dump1090/status"
    assert published[0].payload == ONLINE
    assert published[0].retain is True
    states = [m for m in published if m.topic == "dump1090/aircraft/abc123"]
    assert len(states) == 1
    assert json.loads(states[0].payload) == plane()
    assert states[0].retain is True
    assert states[0].qos == 1


def test_attributes_topic_carries_the_split_payload() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane()])
    attrs = h.client.payloads("dump1090/aircraft/abc123/attributes")
    assert len(attrs) == 1
    decoded = json.loads(attrs[0])
    assert decoded["altitude"] == 34000
    assert decoded["speed"] == 420
    assert decoded["heading"] == 90.0
    assert decoded["squawk"] == "1200"
    assert decoded["flight"] == "BAW117"
    assert decoded["on_ground"] is False


def test_ground_aircraft_reports_zero_altitude() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane(alt_baro="ground")])
    decoded = json.loads(h.client.payloads("dump1090/aircraft/abc123/attributes")[0])
    assert decoded["altitude"] == 0
    assert decoded["on_ground"] is True


def test_count_topic_reflects_aircraft_count() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane(), plane(hex="xyz789")])
    assert h.client.payloads("dump1090/count") == ["2"]
    messages = [m for m in h.client.published if m.topic == "dump1090/count"]
    assert messages[0].retain is True


def test_empty_poll_publishes_zero_count() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([])
    assert h.client.payloads("dump1090/count") == ["0"]


def test_birth_is_not_republished_on_later_polls() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane()])
    h.poll([plane()])
    assert h.client.payloads("dump1090/status") == [ONLINE]


def test_discovery_configs_published_once_per_aircraft() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane()])
    h.poll([plane()])
    assert len(h.client.discovery_topics()) == 4
    altitude_configs = h.client.payloads("homeassistant/sensor/dump1090_abc123_altitude/config")
    assert len(altitude_configs) == 1
    decoded = json.loads(altitude_configs[0])
    assert decoded["unique_id"] == "dump1090_abc123_altitude"
    assert decoded["unit_of_measurement"] == "ft"
    retained = [m for m in h.client.published if m.topic.startswith("homeassistant/")]
    assert all(m.retain for m in retained)


def test_discovery_can_be_disabled() -> None:
    h = Harness(Settings(discovery=False))
    h.publisher.start()
    h.poll([plane()])
    assert h.client.discovery_topics() == []
    assert h.client.payloads("dump1090/aircraft/abc123")


def test_entries_without_a_string_hex_are_skipped() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([{"flight": "NOHEX"}, {"hex": 12345}])
    assert h.client.payloads("dump1090/count") == ["2"]
    assert not any("/aircraft/" in topic for topic in h.client.topics())


def test_non_icao_hex_sanitised_in_every_topic() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane(hex="~A1B2C3")])
    topics = h.client.topics()
    assert "dump1090/aircraft/na1b2c3" in topics
    assert "dump1090/aircraft/na1b2c3/attributes" in topics
    assert "homeassistant/sensor/dump1090_na1b2c3_altitude/config" in topics


def test_custom_topic_prefix_flows_through() -> None:
    h = Harness(Settings(topic_prefix="adsb", discovery_prefix="hass"))
    h.publisher.start()
    h.poll([plane()])
    topics = h.client.topics()
    assert "adsb/status" in topics
    assert "adsb/aircraft/abc123" in topics
    assert "adsb/count" in topics
    assert "hass/sensor/adsb_abc123_altitude/config" in topics


def test_qos_setting_is_applied_to_every_message() -> None:
    h = Harness(Settings(qos=2))
    h.publisher.start()
    h.poll([plane()])
    assert all(message.qos == 2 for message in h.client.published)
    h2 = Harness(Settings(qos=0))
    h2.publisher.start()
    h2.poll([plane()])
    assert all(message.qos == 0 for message in h2.client.published)


# ---------------------------------------------------------------------------
# linger / retire
# ---------------------------------------------------------------------------


def test_retire_clears_retained_state_after_linger() -> None:
    h = Harness(Settings(linger=300))
    h.publisher.start()
    h.poll([plane(hex="abc123")])
    h.clock[0] += 100
    h.poll([plane(hex="xyz789")])
    assert h.client.payloads("dump1090/aircraft/abc123") == [json.dumps(plane(hex="abc123"))]
    h.clock[0] += 300
    h.poll([plane(hex="xyz789")])
    assert h.client.payloads("dump1090/aircraft/abc123")[-1] == ""
    assert h.client.payloads("dump1090/aircraft/abc123/attributes")[-1] == ""
    cleared = [
        m
        for m in h.client.published
        if m.topic in {"dump1090/aircraft/abc123", "dump1090/aircraft/abc123/attributes"}
        and m.payload == ""
    ]
    assert all(m.retain for m in cleared)


def test_no_retire_before_linger_elapses() -> None:
    h = Harness(Settings(linger=300))
    h.publisher.start()
    h.poll([plane(hex="abc123")])
    h.clock[0] += 299
    h.poll([plane(hex="xyz789")])
    assert h.client.payloads("dump1090/aircraft/abc123") == [json.dumps(plane(hex="abc123"))]


def test_linger_zero_retires_immediately() -> None:
    h = Harness(Settings(linger=0))
    h.publisher.start()
    h.poll([plane(hex="abc123")])
    h.poll([plane(hex="xyz789")])
    assert h.client.payloads("dump1090/aircraft/abc123")[-1] == ""


def test_retired_aircraft_gets_discovery_again_on_return() -> None:
    h = Harness(Settings(linger=0))
    h.publisher.start()
    h.poll([plane(hex="abc123")])
    h.poll([plane(hex="xyz789")])
    h.poll([plane(hex="abc123")])
    altitude = "homeassistant/sensor/dump1090_abc123_altitude/config"
    assert len(h.client.payloads(altitude)) == 2


def test_explicit_now_overrides_clock_for_retire() -> None:
    h = Harness(Settings(linger=300))
    h.publisher.start()
    h.poll([plane(hex="abc123")], now=500.0)
    h.poll([plane(hex="xyz789")], now=900.0)
    assert h.client.payloads("dump1090/aircraft/abc123")[-1] == ""


# ---------------------------------------------------------------------------
# reconnect / backoff
# ---------------------------------------------------------------------------


def test_broker_down_skips_poll_with_growing_backoff(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = Harness(connected=False, reconnect_error=OSError("connection refused"))
    h.publisher.start()
    with caplog.at_level(logging.WARNING, logger="dump1090_to_mqtt.publisher"):
        h.poll([plane()])
        h.poll([plane()])
        h.poll([plane()])
    assert h.sleeps == [1.0, 2.0, 4.0]
    assert h.client.reconnect_count == 3
    assert h.client.published == []
    assert any("unreachable" in message for message in caplog.messages)


def test_successful_reconnect_resets_backoff() -> None:
    h = Harness(connected=False, reconnect_error=OSError("down"))
    h.publisher.start()
    h.poll([plane()])
    assert h.sleeps == [1.0]
    h.client.reconnect_error = None
    h.poll([plane()])
    assert h.sleeps == [1.0, 2.0]
    assert h.client.payloads("dump1090/status") == [ONLINE]
    h.client.connected = False
    h.client.reconnect_error = OSError("down")
    h.poll([plane()])
    assert h.sleeps == [1.0, 2.0, 1.0]  # back to the initial delay


def test_nonzero_reconnect_rc_treated_as_failure(caplog: pytest.LogCaptureFixture) -> None:
    h = Harness(connected=False, reconnect_rc=4)
    h.publisher.start()
    with caplog.at_level(logging.WARNING, logger="dump1090_to_mqtt.publisher"):
        h.poll([plane()])
    assert h.sleeps == [1.0]
    assert h.client.published == []
    assert any("rc=4" in message for message in caplog.messages)


def test_publish_rc_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    h = Harness(publish_rc=5)
    h.publisher.start()
    with caplog.at_level(logging.WARNING, logger="dump1090_to_mqtt.publisher"):
        h.poll([plane()])
    assert any("failed" in message for message in caplog.messages)


def test_connection_lost_mid_poll_drops_remaining_messages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class DropsAfterFirst(FakeClient):
        def publish(
            self, topic: str, payload: str | None = None, qos: int = 0, retain: bool = False
        ) -> Any:
            info = super().publish(topic, payload, qos, retain)
            self.connected = False
            return info

    client = DropsAfterFirst()
    publisher = MqttPublisher(
        Settings(), client=client, sleep=lambda _delay: None, now=lambda: 1_000_000.0
    )
    publisher.start()
    with caplog.at_level(logging.WARNING, logger="dump1090_to_mqtt.publisher"):
        publisher.publish_poll([plane()])
    assert client.topics() == ["dump1090/status"]
    assert any("dropping" in message for message in caplog.messages)


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_publishes_offline_then_disconnects() -> None:
    h = Harness()
    h.publisher.start()
    h.poll([plane()])
    h.publisher.stop()
    assert h.client.payloads("dump1090/status") == [ONLINE, OFFLINE]
    offline = [m for m in h.client.published if m.payload == OFFLINE][-1]
    assert offline.retain is True
    assert h.client.disconnect_count == 1
    assert h.client.loop_stops == 1
    assert h.client.events[-2:] == ["disconnect", "loop_stop"]


def test_stop_without_connection_skips_status() -> None:
    h = Harness(connected=False)
    h.publisher.start()
    h.publisher.stop()
    assert h.client.published == []
    assert h.client.disconnect_count == 1
    assert h.client.loop_stops == 1


def test_client_property_exposes_injected_client() -> None:
    h = Harness()
    assert h.publisher.client is h.client


def test_default_construction_builds_paho_v2_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class PahoStub(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            captured.update(kwargs)

    monkeypatch.setattr("dump1090_to_mqtt.client.Client", PahoStub)
    publisher = MqttPublisher(Settings(client_id="my-bridge"))
    assert isinstance(publisher.client, PahoStub)
    assert captured["client_id"] == "my-bridge"
    assert captured["callback_api_version"] is CallbackAPIVersion.VERSION2
    assert captured["reconnect_on_failure"] is True

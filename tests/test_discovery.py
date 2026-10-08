"""Tests for Home Assistant discovery payloads and attribute splitting."""

from __future__ import annotations

import json
from typing import Any

from dump1090_to_mqtt.config import Settings
from dump1090_to_mqtt.discovery import (
    SENSOR_SPECS,
    attributes_payload,
    device_block,
    discovery_payload,
    sensor_messages,
)

ALTITUDE, SPEED, HEADING, SQUAWK = SENSOR_SPECS


# ---------------------------------------------------------------------------
# attributes_payload
# ---------------------------------------------------------------------------


def test_ground_altitude_becomes_zero() -> None:
    payload = attributes_payload({"hex": "ABC123", "alt_baro": "ground"})
    assert payload["altitude"] == 0
    assert payload["on_ground"] is True
    assert payload["hex"] == "abc123"


def test_airborne_altitude_is_numeric() -> None:
    payload = attributes_payload({"hex": "abc123", "alt_baro": 34000})
    assert payload["altitude"] == 34000
    assert payload["on_ground"] is False


def test_speed_prefers_ground_speed_with_fallbacks() -> None:
    assert attributes_payload({"hex": "a", "gs": 420})["speed"] == 420
    assert attributes_payload({"hex": "a", "tas": 415})["speed"] == 415
    assert attributes_payload({"hex": "a", "ias": 300})["speed"] == 300
    # gs wins when several are present
    assert attributes_payload({"hex": "a", "gs": 420, "tas": 415})["speed"] == 420


def test_heading_prefers_track_with_fallbacks() -> None:
    assert attributes_payload({"hex": "a", "track": 180.5})["heading"] == 180.5
    assert attributes_payload({"hex": "a", "mag_heading": 90})["heading"] == 90
    assert attributes_payload({"hex": "a", "true_heading": 91})["heading"] == 91


def test_flight_and_squawk_are_trimmed_strings() -> None:
    payload = attributes_payload({"hex": "a", "flight": " BAW117  ", "squawk": "7700"})
    assert payload["flight"] == "BAW117"
    assert payload["squawk"] == "7700"


def test_missing_fields_are_omitted() -> None:
    assert attributes_payload({}) == {}
    assert "speed" not in attributes_payload({"hex": "a"})
    assert "altitude" not in attributes_payload({"hex": "a"})
    assert "on_ground" not in attributes_payload({"hex": "a"})


def test_non_numeric_values_are_ignored() -> None:
    payload = attributes_payload({"hex": "a", "rssi": "strong", "lat": None, "gs": True})
    assert "rssi" not in payload
    assert "lat" not in payload
    assert "speed" not in payload  # bool is not a number


def test_position_and_message_fields_carry_over() -> None:
    payload = attributes_payload(
        {"hex": "a", "lat": 51.5, "lon": -0.45, "rssi": -4.3, "messages": 120.0}
    )
    assert payload["lat"] == 51.5
    assert payload["lon"] == -0.45
    assert payload["rssi"] == -4.3
    assert payload["messages"] == 120


# ---------------------------------------------------------------------------
# discovery payloads
# ---------------------------------------------------------------------------


def test_altitude_sensor_shape() -> None:
    payload = discovery_payload(Settings(), "abc123", ALTITUDE)
    assert payload["name"] == "Altitude"
    assert payload["unique_id"] == "dump1090_abc123_altitude"
    assert payload["state_topic"] == "dump1090/aircraft/abc123/attributes"
    assert payload["value_template"] == "{{ value_json.altitude }}"
    assert payload["json_attributes_topic"] == "dump1090/aircraft/abc123/attributes"
    assert payload["unit_of_measurement"] == "ft"
    assert payload["state_class"] == "measurement"
    assert "device_class" not in payload
    assert payload["expire_after"] == 600.0
    assert payload["qos"] == 1


def test_speed_sensor_has_speed_device_class() -> None:
    payload = discovery_payload(Settings(), "abc123", SPEED)
    assert payload["device_class"] == "speed"
    assert payload["unit_of_measurement"] == "kn"
    assert payload["value_template"] == "{{ value_json.speed }}"
    assert payload["unique_id"] == "dump1090_abc123_speed"


def test_heading_sensor_uses_degree_unit() -> None:
    payload = discovery_payload(Settings(), "abc123", HEADING)
    assert payload["unit_of_measurement"] == "°"
    assert payload["value_template"] == "{{ value_json.heading }}"
    assert "device_class" not in payload


def test_squawk_sensor_has_no_unit_or_classes() -> None:
    payload = discovery_payload(Settings(), "abc123", SQUAWK)
    assert payload["value_template"] == "{{ value_json.squawk }}"
    assert "unit_of_measurement" not in payload
    assert "device_class" not in payload
    assert "state_class" not in payload


def test_availability_binds_to_status_topic() -> None:
    payload = discovery_payload(Settings(), "abc123", ALTITUDE)
    assert payload["availability"] == [
        {
            "topic": "dump1090/status",
            "payload_available": "online",
            "payload_not_available": "offline",
        }
    ]


def test_device_block_groups_the_four_sensors() -> None:
    device = device_block(Settings(), "abc123")
    assert device["identifiers"] == ["dump1090_abc123"]
    assert device["name"] == "dump1090 abc123"
    assert device["manufacturer"] == "technothatch"
    assert device["model"] == "ADS-B aircraft (dump1090/readsb)"
    assert device["configuration_url"] == "http://localhost:8080"
    for spec in SENSOR_SPECS:
        assert discovery_payload(Settings(), "abc123", spec)["device"] == device


def test_device_block_follows_custom_topic_prefix() -> None:
    device = device_block(Settings(topic_prefix="myradar"), "abc123")
    assert device["identifiers"] == ["myradar_abc123"]
    assert device["name"] == "myradar abc123"


def test_non_icao_hex_sanitised_in_unique_ids() -> None:
    payload = discovery_payload(Settings(), "na1b2c3", ALTITUDE)
    assert payload["unique_id"] == "dump1090_na1b2c3_altitude"
    assert payload["state_topic"] == "dump1090/aircraft/na1b2c3/attributes"


def test_sensor_messages_cover_four_topics_in_order() -> None:
    messages = sensor_messages(Settings(), "abc123")
    assert len(messages) == 4
    topics = [topic for topic, _ in messages]
    assert topics == [
        "homeassistant/sensor/dump1090_abc123_altitude/config",
        "homeassistant/sensor/dump1090_abc123_speed/config",
        "homeassistant/sensor/dump1090_abc123_heading/config",
        "homeassistant/sensor/dump1090_abc123_squawk/config",
    ]


def test_sensor_messages_payloads_are_valid_json_matching_specs() -> None:
    settings = Settings(expire_after=42.0, qos=0)
    messages = sensor_messages(settings, "abc123")
    for (_, payload), spec in zip(messages, SENSOR_SPECS, strict=True):
        decoded: dict[str, Any] = json.loads(payload)
        assert decoded == discovery_payload(settings, "abc123", spec)
        assert decoded["expire_after"] == 42.0
        assert decoded["qos"] == 0


def test_sensor_messages_respect_discovery_prefix() -> None:
    settings = Settings(discovery_prefix="hass", topic_prefix="house/adsb")
    topics = [topic for topic, _ in sensor_messages(settings, "abc123")]
    assert topics[0] == "hass/sensor/house_adsb_abc123_altitude/config"

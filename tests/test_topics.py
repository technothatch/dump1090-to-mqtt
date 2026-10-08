"""Tests for MQTT topic construction and ICAO hex sanitisation."""

from __future__ import annotations

from dump1090_to_mqtt.topics import (
    aircraft_topic,
    attributes_topic,
    count_topic,
    discovery_topic,
    sanitize_hex,
    sensor_node,
    slugify,
    status_topic,
)


def test_sanitize_hex_lowercases_and_trims() -> None:
    assert sanitize_hex("  3C673A  ") == "3c673a"


def test_sanitize_hex_non_icao_tilde_address() -> None:
    assert sanitize_hex("~a1b2c3") == "na1b2c3"
    assert sanitize_hex("~A1B2C3") == "na1b2c3"


def test_sanitize_hex_tilde_can_never_collide_with_real_icao() -> None:
    # "n" is not a hex digit, so the sanitised form of a ~ address is unique.
    assert sanitize_hex("~a1b2c3") != sanitize_hex("a1b2c3")


def test_sanitize_hex_replaces_unsafe_characters() -> None:
    assert sanitize_hex("ab+c#d") == "ab_c_d"
    assert sanitize_hex("a~b") == "a_b"


def test_sanitize_hex_empty_input_is_unknown() -> None:
    assert sanitize_hex("") == "unknown"
    assert sanitize_hex("   ") == "unknown"
    assert sanitize_hex("+#") == "unknown"


def test_slugify() -> None:
    assert slugify("  My Radar! ") == "my_radar"
    assert slugify("dump1090") == "dump1090"
    assert slugify("a/b") == "a_b"


def test_aircraft_and_attributes_topics() -> None:
    assert aircraft_topic("dump1090", "abc123") == "dump1090/aircraft/abc123"
    assert attributes_topic("dump1090", "abc123") == "dump1090/aircraft/abc123/attributes"
    assert attributes_topic("adsb", "na1b2c3") == "adsb/aircraft/na1b2c3/attributes"


def test_status_and_count_topics() -> None:
    assert status_topic("dump1090") == "dump1090/status"
    assert count_topic("dump1090") == "dump1090/count"
    assert status_topic("house/adsb") == "house/adsb/status"


def test_sensor_node_and_discovery_topic() -> None:
    node = sensor_node("dump1090", "abc123", "altitude")
    assert node == "dump1090_abc123_altitude"
    assert discovery_topic("homeassistant", node) == (
        "homeassistant/sensor/dump1090_abc123_altitude/config"
    )


def test_sensor_node_slugs_the_prefix() -> None:
    assert sensor_node("My Radar", "abc123", "squawk") == "my_radar_abc123_squawk"


def test_non_icao_hex_flows_into_topics() -> None:
    hexid = sanitize_hex("~A1B2C3")
    assert aircraft_topic("dump1090", hexid) == "dump1090/aircraft/na1b2c3"
    assert sensor_node("dump1090", hexid, "speed") == "dump1090_na1b2c3_speed"

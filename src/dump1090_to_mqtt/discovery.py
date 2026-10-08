"""Home Assistant MQTT discovery payloads and per-aircraft attribute splits.

One aircraft becomes four ``sensor`` entities (``altitude``, ``speed``,
``heading``, ``squawk``) grouped under a single MQTT device. All four read
from the same ``dump1090/aircraft/<hex>/attributes`` topic with a
``value_template`` selecting their key, and share the bridge's
``dump1090/status`` availability topic, so the whole device flips to
*unavailable* the moment the LWT fires.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dump1090_to_mqtt.config import Settings
from dump1090_to_mqtt.topics import (
    attributes_topic,
    discovery_topic,
    sensor_node,
    slugify,
    status_topic,
)

__all__ = [
    "SENSOR_SPECS",
    "SensorSpec",
    "attributes_payload",
    "device_block",
    "discovery_payload",
    "sensor_messages",
]


@dataclass(frozen=True, slots=True)
class SensorSpec:
    """One Home Assistant sensor derived from an aircraft's attributes."""

    key: str
    label: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None


#: The four sensors published per aircraft, in discovery topic order.
SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(key="altitude", label="Altitude", unit="ft", state_class="measurement"),
    SensorSpec(
        key="speed", label="Speed", unit="kn", device_class="speed", state_class="measurement"
    ),
    SensorSpec(key="heading", label="Heading", unit="°", state_class="measurement"),
    SensorSpec(key="squawk", label="Squawk"),
)


def attributes_payload(aircraft: Mapping[str, Any]) -> dict[str, Any]:
    """Split one raw aircraft object into the sensor attribute dictionary.

    Missing fields are simply absent (Home Assistant then keeps the last
    value until ``expire_after`` flips the entity to unavailable); the
    string ``alt_baro: "ground"`` becomes ``altitude: 0`` with
    ``on_ground: true``.
    """
    out: dict[str, Any] = {}
    hexid = _text(aircraft.get("hex"))
    if hexid is not None:
        out["hex"] = hexid.lower()
    flight = _text(aircraft.get("flight"))
    if flight is not None:
        out["flight"] = flight

    alt = aircraft.get("alt_baro")
    if alt is not None:
        if alt == "ground":
            out["altitude"] = 0
            out["on_ground"] = True
        else:
            value = _number(alt)
            if value is not None:
                out["altitude"] = value
                out["on_ground"] = False

    speed = _first_number(aircraft, "gs", "tas", "ias")
    if speed is not None:
        out["speed"] = speed
    heading = _first_number(aircraft, "track", "mag_heading", "true_heading")
    if heading is not None:
        out["heading"] = heading

    squawk = _text(aircraft.get("squawk"))
    if squawk is not None:
        out["squawk"] = squawk
    rssi = _number(aircraft.get("rssi"))
    if rssi is not None:
        out["rssi"] = rssi
    lat = _number(aircraft.get("lat"))
    if lat is not None:
        out["lat"] = lat
    lon = _number(aircraft.get("lon"))
    if lon is not None:
        out["lon"] = lon
    messages = _number(aircraft.get("messages"))
    if messages is not None:
        out["messages"] = int(messages)
    return out


def device_block(settings: Settings, hexid: str) -> dict[str, Any]:
    """The MQTT device that groups the four sensors of one aircraft."""
    prefix = slugify(settings.topic_prefix)
    return {
        "identifiers": [f"{prefix}_{hexid}"],
        "name": f"{settings.topic_prefix} {hexid}",
        "manufacturer": "technothatch",
        "model": "ADS-B aircraft (dump1090/readsb)",
        "configuration_url": settings.url,
    }


def discovery_payload(settings: Settings, hexid: str, spec: SensorSpec) -> dict[str, Any]:
    """Full ``homeassistant/sensor/<node>/config`` payload for one sensor."""
    state_topic = attributes_topic(settings.topic_prefix, hexid)
    node = sensor_node(settings.topic_prefix, hexid, spec.key)
    payload: dict[str, Any] = {
        "name": spec.label,
        "unique_id": node,
        "state_topic": state_topic,
        "value_template": "{{ value_json." + spec.key + " }}",
        "json_attributes_topic": state_topic,
        "availability": [
            {
                "topic": status_topic(settings.topic_prefix),
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        ],
        "device": device_block(settings, hexid),
        "expire_after": settings.expire_after,
        "qos": settings.qos,
    }
    if spec.unit is not None:
        payload["unit_of_measurement"] = spec.unit
    if spec.device_class is not None:
        payload["device_class"] = spec.device_class
    if spec.state_class is not None:
        payload["state_class"] = spec.state_class
    return payload


def sensor_messages(settings: Settings, hexid: str) -> list[tuple[str, str]]:
    """Every discovery ``(topic, payload)`` pair for one aircraft, as JSON."""
    messages: list[tuple[str, str]] = []
    for spec in SENSOR_SPECS:
        node = sensor_node(settings.topic_prefix, hexid, spec.key)
        topic = discovery_topic(settings.discovery_prefix, node)
        payload = json.dumps(discovery_payload(settings, hexid, spec), ensure_ascii=False)
        messages.append((topic, payload))
    return messages


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _first_number(aircraft: Mapping[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        value = _number(aircraft.get(key))
        if value is not None:
            return value
    return None

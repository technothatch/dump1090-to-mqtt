"""MQTT topic names and ICAO hex sanitisation.

MQTT topic levels may not contain ``+`` or ``#``, and Home Assistant
discovery node ids only accept ``[a-zA-Z0-9_-]``. dump1090/readsb can report
non-ICAO addresses with a leading ``~`` (e.g. ``~a1b2c3``), so every hex is
normalised before it becomes part of a topic or a unique id: lowercased,
trimmed, with the ``~`` rewritten to ``n`` — a character that never occurs in
a real ICAO hex, so sanitised addresses can never collide with real ones.
"""

from __future__ import annotations

import re

__all__ = [
    "NON_ICAO_PREFIX",
    "aircraft_topic",
    "attributes_topic",
    "count_topic",
    "discovery_topic",
    "sanitize_hex",
    "sensor_node",
    "slugify",
    "status_topic",
]

#: Leading marker dump1090/readsb uses for non-ICAO (e.g. TIS-B) addresses.
NON_ICAO_PREFIX = "~"

_UNSAFE_RE = re.compile(r"[^a-z0-9_-]+")


def slugify(text: str) -> str:
    """Lowercase and replace every run of unsafe characters with ``_``."""
    return _UNSAFE_RE.sub("_", text.strip().lower()).strip("_")


def sanitize_hex(raw: str) -> str:
    """Turn a raw ``hex`` field into a topic/identifier-safe string.

    ``3C673A`` becomes ``3c673a``; the non-ICAO address ``~A1B2C3`` becomes
    ``na1b2c3``. Empty input becomes ``unknown`` so a topic is never empty.
    """
    value = raw.strip()
    if value.startswith(NON_ICAO_PREFIX):
        value = "n" + value[1:]
    return slugify(value) or "unknown"


def aircraft_topic(prefix: str, hexid: str) -> str:
    """Full retained JSON state for one aircraft."""
    return f"{prefix}/aircraft/{hexid}"


def attributes_topic(prefix: str, hexid: str) -> str:
    """Split attributes consumed by the Home Assistant discovery sensors."""
    return f"{prefix}/aircraft/{hexid}/attributes"


def status_topic(prefix: str) -> str:
    """Bridge availability (birth/LWT payload: ``online`` / ``offline``)."""
    return f"{prefix}/status"


def count_topic(prefix: str) -> str:
    """Number of aircraft in the most recent poll."""
    return f"{prefix}/count"


def sensor_node(prefix: str, hexid: str, key: str) -> str:
    """Home Assistant discovery node id (and unique_id) for one sensor."""
    return f"{slugify(prefix)}_{hexid}_{key}"


def discovery_topic(discovery_prefix: str, node: str) -> str:
    """Discovery config topic: ``homeassistant/sensor/<node>/config``."""
    return f"{discovery_prefix}/sensor/{node}/config"

"""Publishes dump1090 aircraft state to MQTT: state, attributes, count, status.

Message map (``dump1090`` prefix, all retained):

- ``dump1090/aircraft/<hex>`` — the full raw aircraft object as JSON
- ``dump1090/aircraft/<hex>/attributes`` — split attributes (altitude, speed,
  heading, squawk, flight, rssi, position …) that the Home Assistant
  discovery sensors read through ``value_template``
- ``dump1090/status`` — bridge availability, born ``online``, LWT ``offline``
- ``dump1090/count`` — aircraft in the latest poll
- ``homeassistant/sensor/<node>/config`` — discovery, four sensors per
  aircraft, published once on first sight

Aircraft that vanish from the feed have their retained state cleared after
``linger`` seconds so brokers do not accumulate ghosts; Home Assistant marks
the entities unavailable via ``expire_after`` in the same window. Reconnects
use exponential backoff (:class:`Backoff`) and are skipped per-poll when the
broker is down, so a broker outage never blocks polling.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from paho.mqtt.enums import MQTTErrorCode

from dump1090_to_mqtt.backoff import Backoff
from dump1090_to_mqtt.client import MqttClient, create_client
from dump1090_to_mqtt.config import Settings
from dump1090_to_mqtt.discovery import attributes_payload, sensor_messages
from dump1090_to_mqtt.topics import (
    aircraft_topic,
    attributes_topic,
    count_topic,
    sanitize_hex,
    status_topic,
)

__all__ = ["KEEPALIVE", "OFFLINE", "ONLINE", "MqttPublisher"]

logger = logging.getLogger(__name__)

ONLINE = "online"
OFFLINE = "offline"
KEEPALIVE = 60


class MqttPublisher:
    """Turns polls of ``aircraft.json`` into MQTT messages."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: MqttClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._client = client if client is not None else create_client(settings)
        self._sleep = sleep
        self._now = now
        self._backoff = Backoff(initial=settings.backoff_initial, maximum=settings.backoff_max)
        self._online = False
        self._known: dict[str, float] = {}
        self._discovered: set[str] = set()

    @property
    def client(self) -> MqttClient:
        """The underlying (possibly fake) MQTT client."""
        return self._client

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Register the LWT, apply credentials/TLS, connect and start the loop.

        The will is always set *before* connecting: if this process dies
        uncleanly the broker publishes ``offline`` to ``dump1090/status``
        itself.

        Raises:
            ConnectionError: The broker TCP connection could not be opened.
        """
        settings = self.settings
        if settings.mqtt_username is not None:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.tls:
            self._client.tls_set(ca_certs=settings.tls_ca)
            if settings.tls_insecure:
                self._client.tls_insecure_set(True)
        self._client.will_set(
            status_topic(settings.topic_prefix),
            OFFLINE,
            qos=settings.qos,
            retain=True,
        )
        try:
            self._client.connect(settings.mqtt_host, settings.mqtt_port, KEEPALIVE)
        except OSError as exc:
            raise ConnectionError(
                f"cannot connect to MQTT broker {settings.mqtt_host}:{settings.mqtt_port}: {exc}"
            ) from exc
        self._client.loop_start()

    def stop(self) -> None:
        """Publish the graceful ``offline``, then disconnect and stop the loop."""
        settings = self.settings
        if self._client.is_connected():
            self._client.publish(
                status_topic(settings.topic_prefix),
                OFFLINE,
                qos=settings.qos,
                retain=True,
            )
            self._online = False
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    # -- publishing --------------------------------------------------------
    def publish_poll(self, aircraft: Sequence[dict[str, Any]], *, now: float | None = None) -> None:
        """Publish one snapshot of the ``aircraft`` array.

        Does nothing (beyond a logged warning) while the broker is
        unreachable: the backoff delay is paid once per poll, not once per
        message.
        """
        settings = self.settings
        if not self._ensure_connected():
            logger.warning("MQTT broker unreachable, skipping poll (%d aircraft)", len(aircraft))
            return
        self._sync_status()
        timestamp = self._now() if now is None else now

        seen: set[str] = set()
        for entry in aircraft:
            raw = entry.get("hex")
            if not isinstance(raw, str):
                continue
            hexid = sanitize_hex(raw)
            if hexid == "unknown":
                continue
            seen.add(hexid)
            self._publish(
                aircraft_topic(settings.topic_prefix, hexid),
                json.dumps(entry, ensure_ascii=False),
                retain=True,
            )
            self._publish(
                attributes_topic(settings.topic_prefix, hexid),
                json.dumps(attributes_payload(entry), ensure_ascii=False),
                retain=True,
            )
            if settings.discovery and hexid not in self._discovered:
                for topic, payload in sensor_messages(settings, hexid):
                    self._publish(topic, payload, retain=True)
                self._discovered.add(hexid)
            self._known[hexid] = timestamp

        self._publish(count_topic(settings.topic_prefix), str(len(aircraft)), retain=True)
        self._retire(seen, timestamp)

    def _retire(self, seen: set[str], timestamp: float) -> None:
        """Clear retained state of aircraft unseen for longer than ``linger``."""
        prefix = self.settings.topic_prefix
        stale = [
            (hexid, last)
            for hexid, last in self._known.items()
            if hexid not in seen and timestamp - last >= self.settings.linger
        ]
        for hexid, last in stale:
            self._publish(aircraft_topic(prefix, hexid), "", retain=True)
            self._publish(attributes_topic(prefix, hexid), "", retain=True)
            self._known.pop(hexid, None)
            self._discovered.discard(hexid)
            logger.info("retired %s after %.0fs unseen", hexid, timestamp - last)

    # -- connection handling ----------------------------------------------
    def _ensure_connected(self) -> bool:
        """Return True if connected, otherwise try one backoff-paced reconnect."""
        if self._client.is_connected():
            return True
        delay = self._backoff.next_delay()
        if delay > 0:
            self._sleep(delay)
        try:
            rc = self._client.reconnect()
        except OSError as exc:
            logger.warning("MQTT reconnect failed: %s", exc)
            return False
        if rc != MQTTErrorCode.MQTT_ERR_SUCCESS:
            logger.warning("MQTT reconnect returned rc=%d", int(rc))
            return False
        return self._client.is_connected()

    def _sync_status(self) -> None:
        """Publish the birth ``online`` once connected (and reset backoff)."""
        settings = self.settings
        if not self._client.is_connected():
            self._online = False
            return
        if self._online:
            return
        info = self._client.publish(
            status_topic(settings.topic_prefix),
            ONLINE,
            qos=settings.qos,
            retain=True,
        )
        if info.rc == MQTTErrorCode.MQTT_ERR_SUCCESS:
            self._online = True
            self._backoff.reset()

    def _publish(self, topic: str, payload: str, *, retain: bool = False) -> bool:
        """Publish one message; dropped (and logged) when not connected."""
        if not self._client.is_connected():
            self._online = False
            logger.warning("not connected, dropping %s", topic)
            return False
        info = self._client.publish(topic, payload, qos=self.settings.qos, retain=retain)
        if info.rc != MQTTErrorCode.MQTT_ERR_SUCCESS:
            self._online = False
            logger.warning("publish to %s failed: rc=%d", topic, int(info.rc))
            return False
        return True

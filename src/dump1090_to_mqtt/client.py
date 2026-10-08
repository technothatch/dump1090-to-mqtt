"""The MQTT client surface used by :class:`MqttPublisher`.

:class:`MqttClient` is a :mod:`typing` ``Protocol`` describing exactly the
paho-mqtt 2.x methods the publisher calls, so the broker transport can be
swapped for a fake in tests. :func:`create_client` is the only place that
touches paho directly, and :class:`RecordingClient` captures what would have
been published for ``--dry-run``.
"""

from __future__ import annotations

from typing import Protocol

from paho.mqtt.client import Client, MQTTMessageInfo
from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

from dump1090_to_mqtt.config import Settings

__all__ = ["MqttClient", "RecordingClient", "create_client"]


class MqttClient(Protocol):
    """The subset of ``paho.mqtt.client.Client`` this package relies on."""

    def will_set(
        self, topic: str, payload: str | None = None, qos: int = 0, retain: bool = False
    ) -> None: ...

    def username_pw_set(self, username: str | None, password: str | None = None) -> None: ...

    def tls_set(self, ca_certs: str | None = None) -> None: ...

    def tls_insecure_set(self, value: bool) -> None: ...

    def connect(self, host: str, port: int = 1883, keepalive: int = 60) -> int: ...

    def reconnect(self) -> int: ...

    def disconnect(self) -> int: ...

    def loop_start(self) -> int: ...

    def loop_stop(self) -> int: ...

    def publish(
        self, topic: str, payload: str | None = None, qos: int = 0, retain: bool = False
    ) -> MQTTMessageInfo: ...

    def is_connected(self) -> bool: ...


def create_client(settings: Settings) -> MqttClient:
    """Build the real paho client (callbacks API version 2, MQTT 3.1.1)."""
    client = Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=settings.client_id,
        protocol=MQTTProtocolVersion.MQTTv311,
        reconnect_on_failure=True,
    )
    return client


class RecordingClient:
    """A no-op client that records everything instead of touching a broker.

    Powers ``--dry-run``: the full publish path (state, attributes, count,
    status, discovery) runs for real, the messages are printed instead of
    sent.
    """

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.wills: list[tuple[str, str | None, int, bool]] = []
        self.connect_calls: list[tuple[str, int, int]] = []
        self.credentials: tuple[str | None, str | None] | None = None
        self.tls_calls: list[str | None] = []
        self.tls_insecure = False
        self.connected = False
        self.looping = False
        self.disconnects = 0

    # -- configuration -----------------------------------------------------
    def will_set(
        self, topic: str, payload: str | None = None, qos: int = 0, retain: bool = False
    ) -> None:
        self.wills.append((topic, payload, qos, retain))

    def username_pw_set(self, username: str | None, password: str | None = None) -> None:
        self.credentials = (username, password)

    def tls_set(self, ca_certs: str | None = None) -> None:
        self.tls_calls.append(ca_certs)

    def tls_insecure_set(self, value: bool) -> None:
        self.tls_insecure = value

    # -- lifecycle ---------------------------------------------------------
    def connect(self, host: str, port: int = 1883, keepalive: int = 60) -> int:
        self.connect_calls.append((host, port, keepalive))
        self.connected = True
        return 0

    def reconnect(self) -> int:
        self.connected = True
        return 0

    def disconnect(self) -> int:
        self.connected = False
        self.disconnects += 1
        return 0

    def loop_start(self) -> int:
        self.looping = True
        return 0

    def loop_stop(self) -> int:
        self.looping = False
        return 0

    def is_connected(self) -> bool:
        return self.connected

    # -- publishing --------------------------------------------------------
    def publish(
        self, topic: str, payload: str | None = None, qos: int = 0, retain: bool = False
    ) -> MQTTMessageInfo:
        self.messages.append((topic, payload if payload is not None else ""))
        return MQTTMessageInfo(0)

    def drain(self) -> list[tuple[str, str]]:
        """Return everything published since the last call and clear the log."""
        out = list(self.messages)
        self.messages.clear()
        return out

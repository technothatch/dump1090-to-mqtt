"""A fake paho-mqtt client shared by the test suite.

No test ever touches a broker or a decoder: :class:`FakeClient` records every
call the publisher makes and lets each test script connection state, reconnect
failures and publish return codes.
"""

from __future__ import annotations

from typing import Any

from dump1090_to_mqtt.config import Settings
from dump1090_to_mqtt.publisher import MqttPublisher


class FakeMsgInfo:
    """Stands in for ``paho.mqtt.client.MQTTMessageInfo``."""

    def __init__(self, rc: int = 0) -> None:
        self.rc = rc
        self.published = rc == 0

    def wait_for_publish(self, timeout: float | None = None) -> None:
        return None


class Published:
    """One recorded ``publish`` call."""

    def __init__(self, topic: str, payload: str | None, qos: int, retain: bool) -> None:
        self.topic = topic
        self.payload = "" if payload is None else payload
        self.qos = qos
        self.retain = retain

    def __repr__(self) -> str:
        return f"Published({self.topic!r}, {self.payload!r}, qos={self.qos}, retain={self.retain})"


class FakeClient:
    """Implements the ``MqttClient`` protocol with recorded side effects."""

    def __init__(
        self,
        *,
        connected: bool = True,
        reconnect_rc: int = 0,
        publish_rc: int = 0,
        connect_error: OSError | None = None,
        reconnect_error: OSError | None = None,
    ) -> None:
        self.connected = connected
        self.reconnect_rc = reconnect_rc
        self.publish_rc = publish_rc
        self.connect_error = connect_error
        self.reconnect_error = reconnect_error
        self.events: list[str] = []
        self.wills: list[tuple[str, str | None, int, bool]] = []
        self.credentials: tuple[str | None, str | None] | None = None
        self.tls_calls: list[str | None] = []
        self.tls_insecure_flags: list[bool] = []
        self.connect_calls: list[tuple[str, int, int]] = []
        self.reconnect_count = 0
        self.disconnect_count = 0
        self.loop_starts = 0
        self.loop_stops = 0
        self.published: list[Published] = []

    # -- recording helpers -------------------------------------------------
    def payloads(self, topic: str) -> list[str]:
        return [message.payload for message in self.published if message.topic == topic]

    def topics(self) -> list[str]:
        return [message.topic for message in self.published]

    def discovery_topics(self) -> list[str]:
        return [topic for topic in self.topics() if topic.startswith("homeassistant/")]

    # -- MqttClient protocol ----------------------------------------------
    def will_set(
        self, topic: str, payload: str | None = None, qos: int = 0, retain: bool = False
    ) -> None:
        self.events.append("will_set")
        self.wills.append((topic, payload, qos, retain))

    def username_pw_set(self, username: str | None, password: str | None = None) -> None:
        self.events.append("username_pw_set")
        self.credentials = (username, password)

    def tls_set(self, ca_certs: str | None = None) -> None:
        self.events.append("tls_set")
        self.tls_calls.append(ca_certs)

    def tls_insecure_set(self, value: bool) -> None:
        self.events.append("tls_insecure_set")
        self.tls_insecure_flags.append(value)

    def connect(self, host: str, port: int = 1883, keepalive: int = 60) -> int:
        self.events.append("connect")
        if self.connect_error is not None:
            raise self.connect_error
        self.connect_calls.append((host, port, keepalive))
        return 0

    def reconnect(self) -> int:
        self.events.append("reconnect")
        self.reconnect_count += 1
        if self.reconnect_error is not None:
            raise self.reconnect_error
        if self.reconnect_rc == 0:
            self.connected = True
        return self.reconnect_rc

    def disconnect(self) -> int:
        self.events.append("disconnect")
        self.connected = False
        self.disconnect_count += 1
        return 0

    def loop_start(self) -> int:
        self.events.append("loop_start")
        self.loop_starts += 1
        return 0

    def loop_stop(self) -> int:
        self.events.append("loop_stop")
        self.loop_stops += 1
        return 0

    def publish(
        self, topic: str, payload: str | None = None, qos: int = 0, retain: bool = False
    ) -> FakeMsgInfo:
        self.events.append("publish")
        self.published.append(Published(topic, payload, qos, retain))
        return FakeMsgInfo(self.publish_rc)

    def is_connected(self) -> bool:
        return self.connected


class Harness:
    """A publisher wired to a fake client, a recorded sleeper and a clock."""

    def __init__(self, settings: Settings | None = None, **client_kwargs: object) -> None:
        self.client = FakeClient(**client_kwargs)
        self.sleeps: list[float] = []
        self.clock = [1_000_000.0]
        self.publisher = MqttPublisher(
            settings if settings is not None else Settings(),
            client=self.client,
            sleep=self.sleeps.append,
            now=lambda: self.clock[0],
        )

    def poll(self, aircraft: list[dict[str, Any]], *, now: float | None = None) -> None:
        self.publisher.publish_poll(aircraft, now=now)

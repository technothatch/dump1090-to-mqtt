"""Command-line interface for dump1090-to-mqtt."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from dump1090_to_mqtt import __version__
from dump1090_to_mqtt.client import RecordingClient
from dump1090_to_mqtt.config import ConfigError, resolve_settings
from dump1090_to_mqtt.fetch import DEFAULT_HOST, FetchError, fetch_aircraft
from dump1090_to_mqtt.publisher import MqttPublisher

EXIT_OK = 0
EXIT_ERROR = 1

Fetcher = Callable[..., list[dict[str, Any]]]

__all__ = ["EXIT_ERROR", "EXIT_OK", "build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """The full flag set; every overridable flag defaults to ``None`` so the
    environment (then the built-in default) can win when the flag is absent."""
    parser = argparse.ArgumentParser(
        prog="dump1090-to-mqtt",
        description=(
            "Poll a dump1090 / readsb aircraft.json endpoint and publish aircraft "
            "state to MQTT with Home Assistant discovery."
        ),
        epilog=(
            "Every flag has an environment variable equivalent (see README); flag > env > default."
        ),
    )
    parser.add_argument(
        "--url",
        metavar="URL",
        default=None,
        help=f"decoder base URL or aircraft.json URL (env DUMP1090_URL, default {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        metavar="SECS",
        help="poll interval in seconds (env DUMP1090_INTERVAL, default 2)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SECS",
        help="HTTP timeout in seconds (env DUMP1090_TIMEOUT, default 5)",
    )
    parser.add_argument(
        "--mqtt-host",
        dest="mqtt_host",
        default=None,
        metavar="HOST",
        help="MQTT broker host (env MQTT_HOST, default localhost)",
    )
    parser.add_argument(
        "--mqtt-port",
        dest="mqtt_port",
        type=int,
        default=None,
        metavar="PORT",
        help="MQTT broker port (env MQTT_PORT, default 1883)",
    )
    parser.add_argument(
        "--mqtt-user",
        dest="mqtt_user",
        default=None,
        metavar="USER",
        help="MQTT username (env MQTT_USERNAME)",
    )
    parser.add_argument(
        "--mqtt-password",
        dest="mqtt_password",
        default=None,
        metavar="PASSWORD",
        help="MQTT password (env MQTT_PASSWORD)",
    )
    parser.add_argument(
        "--client-id",
        dest="client_id",
        default=None,
        metavar="ID",
        help="MQTT client id (env MQTT_CLIENT_ID, default dump1090-to-mqtt)",
    )
    parser.add_argument(
        "--topic-prefix",
        dest="topic_prefix",
        default=None,
        metavar="PREFIX",
        help="base for all state topics (env MQTT_TOPIC_PREFIX, default dump1090)",
    )
    parser.add_argument(
        "--discovery-prefix",
        dest="discovery_prefix",
        default=None,
        metavar="PREFIX",
        help="Home Assistant discovery prefix (env HA_DISCOVERY_PREFIX, default homeassistant)",
    )
    parser.add_argument(
        "--qos",
        type=int,
        default=None,
        metavar="N",
        help="MQTT QoS 0-2 (env MQTT_QOS, default 1)",
    )
    parser.add_argument(
        "--discovery",
        dest="discovery",
        action="store_true",
        default=None,
        help="publish Home Assistant discovery configs (env HA_DISCOVERY, default on)",
    )
    parser.add_argument(
        "--no-discovery",
        dest="discovery",
        action="store_false",
        help="do not publish Home Assistant discovery configs",
    )
    parser.add_argument(
        "--linger",
        type=float,
        default=None,
        metavar="SECS",
        help="clear retained state after this many seconds unseen (env MQTT_LINGER, default 300)",
    )
    parser.add_argument(
        "--expire-after",
        dest="expire_after",
        type=float,
        default=None,
        metavar="SECS",
        help="HA sensor expire_after (env HA_EXPIRE_AFTER, default 600)",
    )
    parser.add_argument(
        "--backoff-initial",
        dest="backoff_initial",
        type=float,
        default=None,
        metavar="SECS",
        help="first reconnect delay (env MQTT_BACKOFF_INITIAL, default 1)",
    )
    parser.add_argument(
        "--backoff-max",
        dest="backoff_max",
        type=float,
        default=None,
        metavar="SECS",
        help="maximum reconnect delay (env MQTT_BACKOFF_MAX, default 60)",
    )
    parser.add_argument(
        "--tls",
        dest="tls",
        action="store_true",
        default=None,
        help="enable TLS (env MQTT_TLS)",
    )
    parser.add_argument(
        "--tls-ca",
        dest="tls_ca",
        default=None,
        metavar="PATH",
        help="CA bundle for TLS verification (env MQTT_TLS_CA, requires --tls)",
    )
    parser.add_argument(
        "--tls-insecure",
        dest="tls_insecure",
        action="store_true",
        default=None,
        help="skip TLS certificate verification (env MQTT_TLS_INSECURE)",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print every topic/payload instead of connecting to a broker",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="poll once, publish, then exit",
    )
    parser.add_argument(
        "--max-polls",
        dest="max_polls",
        type=int,
        default=0,
        metavar="N",
        help="stop after N polls (0 = run forever; used by tests)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetcher | None = None,
    publisher: MqttPublisher | None = None,
    sleep: Callable[[float], None] = time.sleep,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Entry point. Returns a process exit code.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
        fetch: Injectable aircraft fetcher for tests.
        publisher: Injectable publisher for tests (never needed with
            ``--dry-run``, which builds a recording client internally).
        sleep: Injectable sleep for tests.
        env: Environment mapping (defaults to ``os.environ``).
        stdout/stderr: Output streams (defaults to the real ones).
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        settings = resolve_settings(args, os.environ if env is None else env)
    except ConfigError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_ERROR

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    fetcher = fetch if fetch is not None else fetch_aircraft
    recorder: RecordingClient | None = None
    if publisher is None:
        if args.dry_run:
            recorder = RecordingClient()
            publisher = MqttPublisher(settings, client=recorder, sleep=sleep)
        else:
            publisher = MqttPublisher(settings, sleep=sleep)

    mode = (
        "dry-run, no MQTT connection"
        if args.dry_run
        else f"mqtt://{settings.mqtt_host}:{settings.mqtt_port}, prefix {settings.topic_prefix}"
    )
    print(f"# {settings.url} -> {mode}, every {settings.interval}s", file=err)

    started = False
    try:
        try:
            publisher.start()
            started = True
        except ConnectionError as exc:
            print(f"error: {exc}", file=err)
            return EXIT_ERROR
        polls = 0
        while True:
            try:
                aircraft = fetcher(settings.url, timeout=settings.timeout)
            except FetchError as exc:
                print(f"error: {exc}", file=err)
                if args.once:
                    return EXIT_ERROR
                polls += 1
                if args.max_polls and polls >= args.max_polls:
                    break
                sleep(settings.interval)
                continue
            publisher.publish_poll(aircraft)
            if recorder is not None:
                for topic, payload in recorder.drain():
                    print(f"{topic} {payload}", file=out)
            polls += 1
            if args.once or (args.max_polls and polls >= args.max_polls):
                break
            sleep(settings.interval)
    except KeyboardInterrupt:
        print("\n# stopped", file=err)
    finally:
        if started:
            publisher.stop()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

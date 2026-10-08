"""Settings for dump1090-to-mqtt: CLI flags resolved over environment variables.

Precedence is always *flag → environment variable → default*. Every problem
(range violations, unparseable numbers, wildcard characters in topic prefixes)
is reported as a :class:`ConfigError` naming the offending flag/environment
variable, never as a traceback.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from dataclasses import dataclass

from dump1090_to_mqtt.fetch import DEFAULT_HOST

__all__ = [
    "DEFAULT_CLIENT_ID",
    "ConfigError",
    "Settings",
    "resolve_settings",
]

DEFAULT_CLIENT_ID = "dump1090-to-mqtt"
DEFAULT_TOPIC_PREFIX = "dump1090"
DEFAULT_DISCOVERY_PREFIX = "homeassistant"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


class ConfigError(Exception):
    """Any problem with a command-line flag or environment variable."""


@dataclass(frozen=True, slots=True)
class Settings:
    """A fully validated configuration."""

    url: str = DEFAULT_HOST
    interval: float = 2.0
    timeout: float = 5.0
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    client_id: str = DEFAULT_CLIENT_ID
    topic_prefix: str = DEFAULT_TOPIC_PREFIX
    discovery_prefix: str = DEFAULT_DISCOVERY_PREFIX
    qos: int = 1
    discovery: bool = True
    linger: float = 300.0
    expire_after: float = 600.0
    backoff_initial: float = 1.0
    backoff_max: float = 60.0
    tls: bool = False
    tls_ca: str | None = None
    tls_insecure: bool = False


def resolve_settings(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from parsed flags plus the environment.

    Flags left at ``None`` (``argparse`` default in this app) fall back to the
    matching environment variable, then to the built-in default.

    Raises:
        ConfigError: A value is unparseable or out of range.
    """
    environ = os.environ if env is None else env
    settings = Settings(
        url=_str(args.url, environ, "DUMP1090_URL", DEFAULT_HOST),
        interval=_float(args.interval, environ, "DUMP1090_INTERVAL", 2.0),
        timeout=_float(args.timeout, environ, "DUMP1090_TIMEOUT", 5.0),
        mqtt_host=_str(args.mqtt_host, environ, "MQTT_HOST", "localhost"),
        mqtt_port=_int(args.mqtt_port, environ, "MQTT_PORT", 1883),
        mqtt_username=_opt_str(args.mqtt_user, environ, "MQTT_USERNAME"),
        mqtt_password=_opt_str(args.mqtt_password, environ, "MQTT_PASSWORD"),
        client_id=_str(args.client_id, environ, "MQTT_CLIENT_ID", DEFAULT_CLIENT_ID),
        topic_prefix=_str(args.topic_prefix, environ, "MQTT_TOPIC_PREFIX", DEFAULT_TOPIC_PREFIX),
        discovery_prefix=_str(
            args.discovery_prefix, environ, "HA_DISCOVERY_PREFIX", DEFAULT_DISCOVERY_PREFIX
        ),
        qos=_int(args.qos, environ, "MQTT_QOS", 1),
        discovery=_boolean(args.discovery, environ, "HA_DISCOVERY", True),
        linger=_float(args.linger, environ, "MQTT_LINGER", 300.0),
        expire_after=_float(args.expire_after, environ, "HA_EXPIRE_AFTER", 600.0),
        backoff_initial=_float(args.backoff_initial, environ, "MQTT_BACKOFF_INITIAL", 1.0),
        backoff_max=_float(args.backoff_max, environ, "MQTT_BACKOFF_MAX", 60.0),
        tls=_boolean(args.tls, environ, "MQTT_TLS", False),
        tls_ca=_opt_str(args.tls_ca, environ, "MQTT_TLS_CA"),
        tls_insecure=_boolean(args.tls_insecure, environ, "MQTT_TLS_INSECURE", False),
    )
    _validate(settings)
    return settings


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def _env_raw(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _str(flag: str | None, env: Mapping[str, str], name: str, default: str) -> str:
    if flag is not None:
        return flag
    return _env_raw(env, name) or default


def _opt_str(flag: str | None, env: Mapping[str, str], name: str) -> str | None:
    if flag is not None:
        return flag
    return _env_raw(env, name)


def _float(flag: float | None, env: Mapping[str, str], name: str, default: float) -> float:
    if flag is not None:
        return flag
    raw = _env_raw(env, name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name}: expected a number, got {raw!r}") from None


def _int(flag: int | None, env: Mapping[str, str], name: str, default: int) -> int:
    if flag is not None:
        return flag
    raw = _env_raw(env, name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name}: expected an integer, got {raw!r}") from None


def _boolean(flag: bool | None, env: Mapping[str, str], name: str, default: bool) -> bool:
    if flag is not None:
        return flag
    raw = _env_raw(env, name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigError(f"{name}: expected a boolean (true/false/1/0/yes/no/on/off), got {raw!r}")


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def _validate(settings: Settings) -> None:
    if not settings.url.startswith(("http://", "https://")):
        raise ConfigError(
            f"DUMP1090_URL/--url must start with http:// or https://, got {settings.url!r}"
        )
    if settings.interval <= 0:
        raise ConfigError(f"DUMP1090_INTERVAL/--interval must be > 0, got {settings.interval}")
    if settings.timeout <= 0:
        raise ConfigError(f"DUMP1090_TIMEOUT/--timeout must be > 0, got {settings.timeout}")
    if not 1 <= settings.mqtt_port <= 65535:
        raise ConfigError(f"MQTT_PORT/--mqtt-port must be 1-65535, got {settings.mqtt_port}")
    if not 0 <= settings.qos <= 2:
        raise ConfigError(f"MQTT_QOS/--qos must be 0, 1 or 2, got {settings.qos}")
    _validate_prefix(settings.topic_prefix, "MQTT_TOPIC_PREFIX/--topic-prefix")
    _validate_prefix(settings.discovery_prefix, "HA_DISCOVERY_PREFIX/--discovery-prefix")
    if not settings.client_id.strip():
        raise ConfigError("MQTT_CLIENT_ID/--client-id must not be empty")
    if settings.linger < 0:
        raise ConfigError(f"MQTT_LINGER/--linger must be >= 0, got {settings.linger}")
    if settings.expire_after <= 0:
        raise ConfigError(
            f"HA_EXPIRE_AFTER/--expire-after must be > 0, got {settings.expire_after}"
        )
    if settings.backoff_initial <= 0:
        raise ConfigError(
            f"MQTT_BACKOFF_INITIAL/--backoff-initial must be > 0, got {settings.backoff_initial}"
        )
    if settings.backoff_max <= 0:
        raise ConfigError(f"MQTT_BACKOFF_MAX/--backoff-max must be > 0, got {settings.backoff_max}")
    if settings.tls_ca is not None and not settings.tls:
        raise ConfigError("MQTT_TLS_CA/--tls-ca requires --tls (MQTT_TLS=true) to be enabled")


def _validate_prefix(prefix: str, where: str) -> None:
    if not prefix.strip():
        raise ConfigError(f"{where} must not be empty")
    if prefix != prefix.strip() or "//" in prefix:
        raise ConfigError(f"{where} must not have surrounding or duplicate slashes, got {prefix!r}")
    for wildcard in ("+", "#"):
        if wildcard in prefix:
            raise ConfigError(f"{where} must not contain {wildcard!r}, got {prefix!r}")

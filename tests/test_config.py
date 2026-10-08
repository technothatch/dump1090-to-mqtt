"""Tests for flag/environment configuration resolution and validation."""

from __future__ import annotations

import pytest

from dump1090_to_mqtt.cli import build_parser
from dump1090_to_mqtt.config import ConfigError, Settings, resolve_settings


def settings_from(argv: list[str] | None = None, env: dict[str, str] | None = None) -> Settings:
    args = build_parser().parse_args(argv or [])
    return resolve_settings(args, env or {})


def error_for(argv: list[str] | None = None, env: dict[str, str] | None = None) -> str:
    with pytest.raises(ConfigError) as excinfo:
        settings_from(argv, env)
    return str(excinfo.value)


# ---------------------------------------------------------------------------
# defaults / env / precedence
# ---------------------------------------------------------------------------


def test_defaults_match_documented_values() -> None:
    settings = settings_from()
    assert settings.url == "http://localhost:8080"
    assert settings.interval == 2.0
    assert settings.timeout == 5.0
    assert settings.mqtt_host == "localhost"
    assert settings.mqtt_port == 1883
    assert settings.mqtt_username is None
    assert settings.mqtt_password is None
    assert settings.client_id == "dump1090-to-mqtt"
    assert settings.topic_prefix == "dump1090"
    assert settings.discovery_prefix == "homeassistant"
    assert settings.qos == 1
    assert settings.discovery is True
    assert settings.linger == 300.0
    assert settings.expire_after == 600.0
    assert settings.backoff_initial == 1.0
    assert settings.backoff_max == 60.0
    assert settings.tls is False
    assert settings.tls_ca is None
    assert settings.tls_insecure is False


def test_environment_overrides_defaults() -> None:
    env = {
        "DUMP1090_URL": "http://decoder.lan:8080",
        "DUMP1090_INTERVAL": "0.5",
        "DUMP1090_TIMEOUT": "1.5",
        "MQTT_HOST": "broker.lan",
        "MQTT_PORT": "8883",
        "MQTT_USERNAME": "user",
        "MQTT_PASSWORD": "secret",
        "MQTT_CLIENT_ID": "bridge-1",
        "MQTT_TOPIC_PREFIX": "adsb",
        "HA_DISCOVERY_PREFIX": "hass",
        "MQTT_QOS": "2",
        "MQTT_LINGER": "60",
        "HA_EXPIRE_AFTER": "120",
        "MQTT_BACKOFF_INITIAL": "0.5",
        "MQTT_BACKOFF_MAX": "10",
        "MQTT_TLS": "true",
        "MQTT_TLS_CA": "/etc/ca.pem",
        "MQTT_TLS_INSECURE": "1",
    }
    settings = settings_from(env=env)
    assert settings.url == "http://decoder.lan:8080"
    assert settings.interval == 0.5
    assert settings.timeout == 1.5
    assert settings.mqtt_host == "broker.lan"
    assert settings.mqtt_port == 8883
    assert settings.mqtt_username == "user"
    assert settings.mqtt_password == "secret"
    assert settings.client_id == "bridge-1"
    assert settings.topic_prefix == "adsb"
    assert settings.discovery_prefix == "hass"
    assert settings.qos == 2
    assert settings.linger == 60.0
    assert settings.expire_after == 120.0
    assert settings.backoff_initial == 0.5
    assert settings.backoff_max == 10.0
    assert settings.tls is True
    assert settings.tls_ca == "/etc/ca.pem"
    assert settings.tls_insecure is True


def test_flags_beat_environment() -> None:
    env = {
        "MQTT_HOST": "env-broker",
        "DUMP1090_URL": "http://env-decoder:8080",
        "MQTT_PORT": "1111",
        "DUMP1090_INTERVAL": "9",
    }
    settings = settings_from(
        [
            "--mqtt-host",
            "flag-broker",
            "--url",
            "http://flag:9999",
            "--mqtt-port",
            "2222",
            "--interval",
            "3.5",
        ],
        env,
    )
    assert settings.mqtt_host == "flag-broker"
    assert settings.url == "http://flag:9999"
    assert settings.mqtt_port == 2222
    assert settings.interval == 3.5


def test_optional_env_values_win_over_empty_flag_absence() -> None:
    settings = settings_from(["--mqtt-user", "flaguser"], {"MQTT_PASSWORD": "envpass"})
    assert settings.mqtt_username == "flaguser"
    assert settings.mqtt_password == "envpass"


def test_empty_env_value_falls_back_to_default() -> None:
    settings = settings_from(env={"MQTT_HOST": "", "MQTT_PORT": "   "})
    assert settings.mqtt_host == "localhost"
    assert settings.mqtt_port == 1883


def test_reads_process_environment_when_env_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_HOST", "from-os-environ")
    args = build_parser().parse_args([])
    settings = resolve_settings(args)
    assert settings.mqtt_host == "from-os-environ"


# ---------------------------------------------------------------------------
# boolean handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_true_boolean_env(raw: str) -> None:
    assert settings_from(env={"MQTT_TLS": raw}).tls is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "no", "off"])
def test_false_boolean_env(raw: str) -> None:
    assert settings_from(env={"MQTT_TLS": raw, "HA_DISCOVERY": raw}).tls is False
    assert settings_from(env={"MQTT_TLS": raw, "HA_DISCOVERY": raw}).discovery is False


def test_invalid_boolean_env_names_the_variable() -> None:
    message = error_for(env={"MQTT_TLS": "maybe"})
    assert "MQTT_TLS" in message
    assert "expected a boolean" in message


def test_no_discovery_flag_disables_discovery() -> None:
    assert settings_from(["--no-discovery"]).discovery is False
    assert settings_from(["--discovery"], {"HA_DISCOVERY": "false"}).discovery is True


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_invalid_integer_env_names_the_variable() -> None:
    assert "MQTT_PORT" in error_for(env={"MQTT_PORT": "not-a-port"})
    assert "MQTT_QOS" in error_for(env={"MQTT_QOS": "one"})


def test_port_out_of_range() -> None:
    message = error_for(env={"MQTT_PORT": "70000"})
    assert "1-65535" in message
    assert "70000" in message
    assert "1-65535" in error_for(["--mqtt-port", "0"])


def test_invalid_float_env() -> None:
    assert "DUMP1090_INTERVAL" in error_for(env={"DUMP1090_INTERVAL": "fast"})


@pytest.mark.parametrize("value", ["0", "-1"])
def test_interval_must_be_positive(value: str) -> None:
    message = error_for(["--interval", value])
    assert "--interval must be > 0" in message


def test_timeout_must_be_positive() -> None:
    assert "--timeout must be > 0" in error_for(env={"DUMP1090_TIMEOUT": "0"})


def test_qos_range() -> None:
    message = error_for(env={"MQTT_QOS": "3"})
    assert "0, 1 or 2" in message
    assert "0, 1 or 2" in error_for(["--qos", "-1"])


def test_url_must_be_http() -> None:
    message = error_for(["--url", "ftp://decoder"])
    assert "must start with http" in message


def test_empty_topic_prefix_rejected() -> None:
    assert "must not be empty" in error_for(["--topic-prefix", ""])


@pytest.mark.parametrize("bad", ["ad#b", "ad+b"])
def test_wildcards_in_prefix_rejected(bad: str) -> None:
    message = error_for(["--topic-prefix", bad])
    assert "must not contain" in message


def test_bad_slashes_in_prefix_rejected() -> None:
    assert "duplicate slashes" in error_for(["--topic-prefix", "a//b"])
    assert "surrounding" in error_for(["--discovery-prefix", " x"])


def test_empty_client_id_rejected() -> None:
    assert "client-id" in error_for(["--client-id", "  "])


def test_linger_must_not_be_negative() -> None:
    message = error_for(env={"MQTT_LINGER": "-5"})
    assert "--linger must be >= 0" in message


def test_expire_after_must_be_positive() -> None:
    assert "--expire-after must be > 0" in error_for(["--expire-after", "0"])


def test_backoff_values_must_be_positive() -> None:
    assert "--backoff-initial must be > 0" in error_for(env={"MQTT_BACKOFF_INITIAL": "0"})
    assert "--backoff-max must be > 0" in error_for(env={"MQTT_BACKOFF_MAX": "-2"})


def test_tls_ca_requires_tls() -> None:
    message = error_for(["--tls-ca", "/etc/ca.pem"])
    assert "requires --tls" in message
    settings = settings_from(["--tls", "--tls-ca", "/etc/ca.pem"])
    assert settings.tls is True
    assert settings.tls_ca == "/etc/ca.pem"


def test_valid_linger_zero_allowed() -> None:
    assert settings_from(["--linger", "0"]).linger == 0.0


def test_settings_is_immutable() -> None:
    settings = Settings()
    with pytest.raises(Exception):  # noqa: B017
        settings.qos = 2  # type: ignore[misc]

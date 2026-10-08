# dump1090-to-mqtt

[![CI](https://github.com/technothatch/dump1090-to-mqtt/actions/workflows/ci.yml/badge.svg)](https://github.com/technothatch/dump1090-to-mqtt/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/technothatch/dump1090-to-mqtt/blob/main/LICENSE)
[![Latest Release](https://img.shields.io/github/v/release/technothatch/dump1090-to-mqtt)](https://github.com/technothatch/dump1090-to-mqtt/releases)
[![Issues](https://img.shields.io/github/issues/technothatch/dump1090-to-mqtt)](https://github.com/technothatch/dump1090-to-mqtt/issues)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/technothatch/dump1090-to-mqtt/pulls)
[![Code size](https://img.shields.io/github/languages/code-size/technothatch/dump1090-to-mqtt)](https://github.com/technothatch/dump1090-to-mqtt)
[![Last commit](https://img.shields.io/github/last-commit/technothatch/dump1090-to-mqtt)](https://github.com/technothatch/dump1090-to-mqtt/commits/main)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://img.shields.io/badge/coverage-97%25-brightgreen.svg)](https://github.com/technothatch/dump1090-to-mqtt)

A small bridge that polls the `aircraft.json` published by
[dump1090](https://github.com/flightaware/dump1090) and
[readsb](https://github.com/wiedehopf/readsb) and publishes every aircraft to
MQTT, with first-class [Home Assistant](https://www.home-assistant.io/) MQTT
discovery. Each aircraft becomes one device with four sensors — altitude,
speed, heading and squawk — that appear in Home Assistant automatically, no
YAML required. The bridge announces its own availability through a
last-will/test-will on `dump1090/status`, so Home Assistant marks everything
*unavailable* the moment the process or broker dies, and it survives broker
outages with exponential reconnect backoff. One process, one dependency
(`paho-mqtt`), standard-library HTTP polling.

## Features

- **Four topics per aircraft** — `dump1090/aircraft/<hex>` (full raw JSON,
  retained), `dump1090/aircraft/<hex>/attributes` (split fields for Home
  Assistant), `dump1090/count`, and `dump1090/status` (birth/LWT
  `online`/`offline`).
- **Home Assistant MQTT discovery** — `homeassistant/sensor/<node>/config`
  for `altitude` (ft), `speed` (kn, `device_class: speed`), `heading` (°) and
  `squawk`, all grouped under one device block with stable `unique_id`s and
  shared availability.
- **Retained, self-cleaning state** — aircraft that leave the feed have their
  retained topics cleared after `--linger` seconds, and HA entities expire
  via `expire_after`, so the broker never accumulates ghosts.
- **Non-ICAO addresses handled** — readsb's `~a9f01c` style hexes are
  sanitised into topic-safe, collision-free ids (`na9f01c`).
- **Reconnects with exponential backoff** — 1 s → 2 s → 4 s … capped at
  `--backoff-max`, reset on success; a broker outage skips polls instead of
  blocking them.
- **Config via flags or environment** — every flag has an env-var
  equivalent (flag > env > default), so the bridge drops into systemd,
  Docker or a cron line.
- **`--dry-run` prints everything** — the real publish path runs against a
  recording client and prints `topic payload` lines instead of touching a
  broker: perfect for checking a config or capturing README output.
- **Fully typed, 132 tests at 97% coverage** — MQTT client injected as a
  protocol; no test needs a broker or a decoder.

## Install

```bash
pip install dump1090-to-mqtt
```

Or from source:

```bash
git clone https://github.com/technothatch/dump1090-to-mqtt.git
cd dump1090-to-mqtt
pip install -e ".[dev]"
```

Requires Python 3.11+ and an MQTT broker (e.g. Mosquitto). Home Assistant
integration is optional.

## Quickstart

See exactly what will be published — no broker needed:

```console
$ dump1090-to-mqtt --dry-run --once
# http://localhost:8080 -> dry-run, no MQTT connection, every 2.0s
dump1090/status online
dump1090/aircraft/3c673a {"hex": "3c673a", "type": "adsb_icao", "flight": "BAW117  ", "alt_baro": 31000, ... "rssi": -4.3}
dump1090/aircraft/3c673a/attributes {"hex": "3c673a", "flight": "BAW117", "altitude": 31000, "on_ground": false, "speed": 421.3, "heading": 97.5, "squawk": "1200", "rssi": -4.3, "lat": 51.4712, "lon": -0.4543, "messages": 4123}
homeassistant/sensor/dump1090_3c673a_altitude/config {"name": "Altitude", "unique_id": "dump1090_3c673a_altitude", "state_topic": "dump1090/aircraft/3c673a/attributes", ...}
...  (3 more discovery configs, then one block per further aircraft — a non-ICAO `~a9f01c` on the ground becomes `na9f01c`)
dump1090/count 2
```

Then run it for real against your broker:

```console
$ dump1090-to-mqtt --mqtt-host 192.168.1.10 --mqtt-user mqtt --mqtt-password secret
# http://localhost:8080 -> mqtt://192.168.1.10:1883, prefix dump1090, every 2.0s
```

Watch the traffic flow (Mosquitto CLI):

```bash
mosquitto_sub -h 192.168.1.10 -t 'dump1090/#' -v
# dump1090/status online
# dump1090/count 2
# dump1090/aircraft/3c673a {"hex": "3c673a", ...}
```

In Home Assistant: *Settings → Devices & services → MQTT* must already be
configured. Start the bridge once and four sensors per aircraft appear under
a `dump1090 <hex>` device — no YAML, no restart.

Point it at another decoder with `--url` or `DUMP1090_URL`; both accept a
bare base URL or a full `.../data/aircraft.json` document URL.

## Configuration reference

Every flag maps to an environment variable. Precedence: **flag > env >
default**.

### Command line / environment

| Flag | Environment | Meaning | Default |
| --- | --- | --- | --- |
| `--url URL` | `DUMP1090_URL` | Decoder base URL or `aircraft.json` URL | `http://localhost:8080` |
| `--interval SECS` | `DUMP1090_INTERVAL` | Poll interval | `2.0` |
| `--timeout SECS` | `DUMP1090_TIMEOUT` | HTTP timeout | `5.0` |
| `--mqtt-host HOST` | `MQTT_HOST` | MQTT broker host | `localhost` |
| `--mqtt-port PORT` | `MQTT_PORT` | MQTT broker port | `1883` |
| `--mqtt-user USER` | `MQTT_USERNAME` | MQTT username | — |
| `--mqtt-password PASS` | `MQTT_PASSWORD` | MQTT password | — |
| `--client-id ID` | `MQTT_CLIENT_ID` | MQTT client id | `dump1090-to-mqtt` |
| `--topic-prefix PREFIX` | `MQTT_TOPIC_PREFIX` | Base of all state topics | `dump1090` |
| `--discovery-prefix PREFIX` | `HA_DISCOVERY_PREFIX` | Home Assistant discovery prefix | `homeassistant` |
| `--qos N` | `MQTT_QOS` | MQTT QoS (`0`–`2`) | `1` |
| `--discovery` / `--no-discovery` | `HA_DISCOVERY` | Publish HA discovery configs | on |
| `--linger SECS` | `MQTT_LINGER` | Clear retained state after this long unseen | `300` |
| `--expire-after SECS` | `HA_EXPIRE_AFTER` | HA `expire_after` for the sensors | `600` |
| `--backoff-initial SECS` | `MQTT_BACKOFF_INITIAL` | First reconnect delay | `1.0` |
| `--backoff-max SECS` | `MQTT_BACKOFF_MAX` | Maximum reconnect delay | `60.0` |
| `--tls` | `MQTT_TLS` | Enable TLS | off |
| `--tls-ca PATH` | `MQTT_TLS_CA` | CA bundle (requires `--tls`) | system roots |
| `--tls-insecure` | `MQTT_TLS_INSECURE` | Skip certificate verification | off |
| `--dry-run` | — | Print topics/payloads, no broker | off |
| `--once` | — | Single poll, then exit | off |
| `--max-polls N` | — | Stop after N polls (`0` = forever) | `0` |
| `--version` | — | Print version and exit | — |

Boolean env values accept `1/0`, `true/false`, `yes/no`, `on/off`.
Invalid values fail fast with an error naming the variable
(`error: MQTT_PORT: expected an integer, got 'nope'`), before any connection
is attempted.

### Topics

| Topic | Payload | Retained |
| --- | --- | --- |
| `dump1090/aircraft/<hex>` | the full aircraft object, verbatim JSON | yes |
| `dump1090/aircraft/<hex>/attributes` | split fields: `altitude`, `speed`, `heading`, `squawk`, `flight`, `rssi`, `lat`, `lon`, `on_ground`, … | yes |
| `dump1090/status` | `online` (birth) / `offline` (graceful stop or LWT) | yes |
| `dump1090/count` | number of aircraft in the latest poll | yes |
| `homeassistant/sensor/<node>/config` | HA discovery, 4 sensors per aircraft | yes |

`<hex>` is the lowercased ICAO address; a non-ICAO `~a9f01c` becomes
`na9f01c`. `alt_baro: "ground"` becomes `altitude: 0` with
`on_ground: true` in the attributes topic.

### Home Assistant discovery

One payload per sensor, published on first sight of an aircraft
(`homeassistant/sensor/dump1090_3c673a_altitude/config`):

```json
{
  "name": "Altitude",
  "unique_id": "dump1090_3c673a_altitude",
  "state_topic": "dump1090/aircraft/3c673a/attributes",
  "value_template": "{{ value_json.altitude }}",
  "json_attributes_topic": "dump1090/aircraft/3c673a/attributes",
  "availability": [
    {
      "topic": "dump1090/status",
      "payload_available": "online",
      "payload_not_available": "offline"
    }
  ],
  "device": {
    "identifiers": ["dump1090_3c673a"],
    "name": "dump1090 3c673a",
    "manufacturer": "technothatch",
    "model": "ADS-B aircraft (dump1090/readsb)",
    "configuration_url": "http://localhost:8080"
  },
  "expire_after": 600.0,
  "qos": 1,
  "unit_of_measurement": "ft",
  "state_class": "measurement"
}
```

The `speed` sensor adds `"device_class": "speed"` and `"unit_of_measurement":
"kn"`, `heading` uses `°`, and `squawk` has no unit or device class. All four
share the `device` block, so they group into one entry in Home Assistant, and
all four read the same attributes topic through their `value_template`.

## How it works

```
   aircraft.json
   ─────────────▶ fetch.py ──▶ publisher.py ──▶ MQTT broker ──▶ Home Assistant
   (urllib,          │            │                               │
    resolves URL,    │            │ per-poll:                      │  4 sensors
    tolerant shape)  │            │  state + attributes + count    │  per device,
                     ▼            ▼  + discovery on first sight    │  availability
               topics.py     client.py ◀── Backoff (1s → 2s → 4s…) │  from
               sanitize_hex  MqttClient protocol / paho-mqtt 2.x   │  dump1090/
               topic names        │                                │  status
                                  ▼
                             cli.py — flags/env, poll loop,
                             --dry-run (RecordingClient), --once
```

- **`fetch.py` / `topics.py` / `discovery.py` are pure** — no sockets, no
  clock, which is why payload construction, topic naming and hex
  sanitisation are exhaustively testable.
- **`client.py` isolates paho** — `MqttClient` is a `Protocol`; the publisher
  only ever sees that surface, tests inject a fake, and `--dry-run` swaps in
  a `RecordingClient`. The real client is built exactly once, with
  `CallbackAPIVersion.VERSION2`.
- **`publisher.py` owns the MQTT state machine** — the LWT (`offline`) is
  registered *before* connecting, the birth (`online`) is published (retained)
  as soon as the connection is up and resets the backoff, `stop()` publishes a
  graceful `offline`, and each poll first checks connectivity: one backoff
  sleep per *poll* when the broker is down, never per message.
- **`cli.py` wires it together** — flag/env resolution that fails fast with a
  named error, the poll loop, `--once`/`--max-polls` for scripts, and
  `--dry-run`.

## Development

```bash
git clone https://github.com/technothatch/dump1090-to-mqtt.git
cd dump1090-to-mqtt
pip install -e ".[dev]"

make lint     # ruff check + ruff format --check + mypy
make test     # pytest with coverage (fail-under 80)
make check    # everything, the same gate CI runs
```

The test suite covers payload construction, topic naming, HA discovery JSON
shape (device block, unit/device classes, unique ids), `~` hex
sanitisation, status/LWT transitions, reconnect backoff with an injected
clock and sleeper, linger/retire, config parsing from flags and env, and the
CLI loop — 132 tests at 97% line and branch coverage. The MQTT client and
HTTP are mocked; no test requires a running broker or decoder.

## Related projects

- [dump1090-fa](https://github.com/flightaware/dump1090) — FlightAware's decoder
- [readsb](https://github.com/wiedehopf/readsb) — high-performance fork, JSON docs in-repo
- [tar1090](https://github.com/wiedehopf/tar1090) — web UI for readsb
- [graphs1090](https://github.com/wiedehopf/graphs1090) — statistics graphs
- [dump1090-alerts](https://github.com/technothatch/dump1090-alerts) — rule-based notifications
- [squawk-decoder](https://github.com/technothatch/squawk-decoder) — what a squawk code means

## License

MIT © technothatch. See [LICENSE](LICENSE).

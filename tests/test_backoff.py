"""Tests for the exponential reconnect backoff."""

from __future__ import annotations

from dump1090_to_mqtt.backoff import Backoff


def test_backoff_doubles_until_cap() -> None:
    backoff = Backoff(initial=1.0, factor=2.0, maximum=60.0)
    delays = [backoff.next_delay() for _ in range(9)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]


def test_backoff_reset_restarts_sequence() -> None:
    backoff = Backoff(initial=1.0, factor=2.0, maximum=60.0)
    backoff.next_delay()
    backoff.next_delay()
    backoff.reset()
    assert backoff.next_delay() == 1.0


def test_backoff_clamps_initial_above_maximum() -> None:
    backoff = Backoff(initial=100.0, factor=3.0, maximum=30.0)
    assert backoff.next_delay() == 30.0
    assert backoff.next_delay() == 30.0


def test_backoff_factor_one_is_constant() -> None:
    backoff = Backoff(initial=2.5, factor=1.0, maximum=10.0)
    assert [backoff.next_delay() for _ in range(4)] == [2.5, 2.5, 2.5, 2.5]


def test_backoff_attempt_counter_advances() -> None:
    backoff = Backoff(initial=1.0, factor=2.0, maximum=60.0)
    assert backoff.attempt == 0
    backoff.next_delay()
    assert backoff.attempt == 1
    backoff.next_delay()
    assert backoff.attempt == 2
    backoff.reset()
    assert backoff.attempt == 0


def test_backoff_fractional_growth() -> None:
    backoff = Backoff(initial=0.5, factor=3.0, maximum=100.0)
    assert [backoff.next_delay() for _ in range(3)] == [0.5, 1.5, 4.5]

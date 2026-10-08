"""Exponential backoff for MQTT reconnect attempts."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Backoff"]


@dataclass(slots=True)
class Backoff:
    """Growing delay between reconnect attempts, capped at ``maximum``.

    Each call to :meth:`next_delay` returns the delay for the next attempt and
    advances the attempt counter; the sequence is ``initial``,
    ``initial * factor``, ``initial * factor**2``, … clamped to ``maximum``.
    :meth:`reset` is called once the broker is reachable again so the next
    outage starts small instead of waiting a full minute.
    """

    initial: float = 1.0
    factor: float = 2.0
    maximum: float = 60.0
    attempt: int = 0

    def next_delay(self) -> float:
        """Delay to sleep before the next reconnect attempt, in seconds."""
        delay = min(self.initial * (self.factor**self.attempt), self.maximum)
        self.attempt += 1
        return delay

    def reset(self) -> None:
        """Restart the sequence after a successful connection."""
        self.attempt = 0

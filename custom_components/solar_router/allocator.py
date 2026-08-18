"""The allocation logic, deliberately free of Home Assistant.

Keeping this pure means it can be reasoned about and tested on its own. The
coordinator does the talking to Home Assistant; this file only decides.

A consumer is described by what you can actually control:

  number only   a dial. Zero means off, so no switch is needed.
  switch only   on or off at a fixed draw.
  both          a switch to enable it and a dial to set how hard it runs.

You fill in whichever you have; the mode follows from that.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Consumer:
    """One thing that can absorb surplus power."""

    key: str
    priority: int
    power_min: float
    power_max: float
    has_number: bool = False
    has_switch: bool = False
    managed: bool = True
    # runtime
    currently_on: bool = False
    allocated: float = 0.0
    held: bool = False  # inside its minimum on/off window

    @property
    def modulating(self) -> bool:
        """A dial makes it modulating, with or without a switch beside it."""
        return self.has_number


@dataclass
class Decision:
    """What should happen to one consumer this cycle.

    number_value is None when there is nothing to dial, switch_on is None when
    there is no switch or it is already in the right position.
    """

    key: str
    allocated: float
    reason: str
    number_value: float | None = None
    switch_on: bool | None = None


def budget_from(grid_export: float, already_allocated: float, reserve: float) -> float:
    """Power we may spend.

    grid_export is positive when exporting. We add back what our own consumers
    are drawing, because that draw is why the export is not higher. Forgetting
    this is what makes naive versions oscillate.
    """
    return grid_export + already_allocated - reserve


def _decide_one(c: Consumer, remaining: float) -> Decision:
    """Work out what this consumer gets from what is left."""
    if not c.managed:
        return Decision(c.key, 0.0, "not managed")

    if c.modulating:
        give = max(0.0, min(c.power_max, remaining))
        if give < c.power_min:
            give = 0.0

        d = Decision(c.key, give, "modulating" if give else "below minimum")

        # Only dial when it actually moved, to avoid pointless service calls.
        if abs(give - c.allocated) >= 1:
            d.number_value = give

        # A switch beside the dial is used as the on/off gate.
        if c.has_switch:
            want_on = give > 0
            if want_on != c.currently_on:
                if c.held:
                    # Respect the minimum on/off window: keep the current
                    # position and hand the power back if we cannot start.
                    d.reason = "held on" if c.currently_on else "held off"
                    if not c.currently_on:
                        d.allocated = 0.0
                        d.number_value = None
                    return d
                d.switch_on = want_on
        return d

    # switch only: all or nothing at its rated draw
    rated = c.power_max or c.power_min
    if c.currently_on:
        if remaining >= 0 or c.held:
            return Decision(c.key, rated, "on" if remaining >= 0 else "held on")
        return Decision(c.key, 0.0, "shortfall", switch_on=False)

    if remaining >= rated and not c.held:
        return Decision(c.key, rated, "surplus available", switch_on=True)

    return Decision(c.key, 0.0, "held off" if c.held else "waiting for surplus")


def allocate(budget: float, consumers: list[Consumer]) -> list[Decision]:
    """Hand the budget out in priority order (lower number first)."""
    decisions: list[Decision] = []
    remaining = budget

    for c in sorted(consumers, key=lambda x: x.priority):
        d = _decide_one(c, remaining)
        decisions.append(d)
        remaining -= d.allocated

    return decisions


def unused(budget: float, decisions: list[Decision]) -> float:
    """Surplus nobody claimed."""
    return max(0.0, budget - sum(d.allocated for d in decisions))

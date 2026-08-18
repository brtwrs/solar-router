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
    allocated: float = 0.0  # what the dial is set to right now
    measured: float | None = None  # what it actually draws, if we can see it
    held: bool = False  # inside its minimum on/off window

    @property
    def modulating(self) -> bool:
        """A dial makes it modulating, with or without a switch beside it."""
        return self.has_number


@dataclass
class Decision:
    """What should happen to one consumer this cycle.

    allocated is what we are giving it. claim is what it actually costs us,
    which differs when a device is allowed 3 kW but its own thermostat has cut
    out and it draws nothing. Counting the allocation instead of the real draw
    would double count that power and send us into import.

    number_value is None when there is nothing to dial, switch_on is None when
    there is no switch or it is already in the right position.
    """

    key: str
    allocated: float
    reason: str
    number_value: float | None = None
    switch_on: bool | None = None
    claim: float = 0.0


def budget_from(grid_export: float, already_allocated: float, reserve: float) -> float:
    """Power we may spend.

    grid_export is positive when exporting. We add back what our own consumers
    are drawing, because that draw is why the export is not higher. Forgetting
    this is what makes naive versions oscillate.
    """
    return grid_export + already_allocated - reserve


def _claim_for(c: Consumer, allocated: float) -> float:
    """What this consumer really costs the budget.

    With a power sensor we use the measured draw, capped at what we allowed —
    anything above that is not ours to account for. Without one we can only
    assume it uses what it was given.
    """
    if c.measured is None:
        return allocated
    return max(0.0, min(c.measured, allocated))


def _decide_one(c: Consumer, remaining: float) -> Decision:
    """Work out what this consumer gets from what is left."""
    if not c.managed:
        return Decision(c.key, 0.0, "not managed", claim=0.0)

    if c.modulating:
        give = max(0.0, min(c.power_max, remaining))
        if give < c.power_min:
            give = 0.0

        d = Decision(c.key, give, "modulating" if give else "below minimum")
        d.claim = _claim_for(c, give)
        if c.measured is not None and give and d.claim < give * 0.2:
            # Allowed to draw but barely using it: its own thermostat or
            # charger has backed off. Say so, and let the rest have the power.
            d.reason = "allowed, not drawing"

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
                        d.claim = 0.0
                    return d
                d.switch_on = want_on
        return d

    # switch only: all or nothing at its rated draw
    rated = c.power_max or c.power_min
    if c.currently_on:
        if remaining >= 0 or c.held:
            d = Decision(c.key, rated, "on" if remaining >= 0 else "held on")
            d.claim = _claim_for(c, rated)
            if c.measured is not None and d.claim < rated * 0.2:
                d.reason = "allowed, not drawing"
            return d
        return Decision(c.key, 0.0, "shortfall", switch_on=False, claim=0.0)

    if remaining >= rated and not c.held:
        return Decision(c.key, rated, "surplus available", switch_on=True, claim=rated)

    return Decision(
        c.key, 0.0, "held off" if c.held else "waiting for surplus", claim=0.0
    )


def allocate(budget: float, consumers: list[Consumer]) -> list[Decision]:
    """Hand the budget out in priority order (lower number first)."""
    decisions: list[Decision] = []
    remaining = budget

    for c in sorted(consumers, key=lambda x: x.priority):
        d = _decide_one(c, remaining)
        decisions.append(d)
        remaining -= d.claim

    return decisions


def unused(budget: float, decisions: list[Decision]) -> float:
    """Surplus nobody claimed."""
    return max(0.0, budget - sum(d.claim for d in decisions))

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


def should_settle(
    grid_updated_at: float | None,
    last_action_at: float | None,
    now: float,
    settle: float = 0.0,
) -> bool:
    """True when we should keep our hands still and wait.

    After changing something, the grid meter still reports the world as it was
    before. Deciding again on that stale reading is how you overshoot: you see
    no effect, push harder, and then have to unwind it.

    So we wait for a reading that is genuinely newer than our last action.
    Timestamps are seconds; settle adds a margin for devices that take a while
    to actually ramp up.

    Never having acted means there is nothing to wait for.
    """
    if last_action_at is None:
        return False
    if now - last_action_at < settle:
        return True
    if grid_updated_at is None:
        return True
    return grid_updated_at <= last_action_at


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


def _demp(huidig: float, doel: float, gain: float) -> float:
    """Beweeg maar een deel van de afstand naar het doel.

    Springen naar precies wat het budget toelaat gaat mis zodra de meting en
    het werkelijke verbruik niet gelijk lopen: je schiet erover heen, corrigeert
    te ver terug, en slingert. Met een versterking onder 1 nader je het doel in
    stappen en dooft de slinger uit.

    gain 1.0 schakelt dit uit.
    """
    if gain >= 1.0:
        return doel
    return huidig + (doel - huidig) * gain


def _decide_one(c: Consumer, remaining: float, gain: float = 1.0) -> Decision:
    """Work out what this consumer gets from what is left."""
    if not c.managed:
        return Decision(c.key, 0.0, "not managed", claim=0.0)

    if c.modulating:
        doel = max(0.0, min(c.power_max, remaining))
        give = _demp(c.allocated, doel, gain)
        give = max(0.0, min(c.power_max, give))

        # Onder het minimum heeft dempen geen zin: dan is uit ook echt uit.
        if doel < c.power_min:
            give = 0.0
        elif give < c.power_min:
            give = c.power_min

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


def allocate(
    budget: float, consumers: list[Consumer], gain: float = 1.0
) -> list[Decision]:
    """Hand the budget out in priority order (lower number first).

    gain onder 1 laat modulerende verbruikers stapsgewijs naar hun doel
    bewegen in plaats van er in een keer heen te springen.
    """
    decisions: list[Decision] = []
    remaining = budget

    for c in sorted(consumers, key=lambda x: x.priority):
        d = _decide_one(c, remaining, gain)
        decisions.append(d)
        remaining -= d.claim

    return decisions


def unused(budget: float, decisions: list[Decision]) -> float:
    """Surplus nobody claimed."""
    return max(0.0, budget - sum(d.claim for d in decisions))

"""Talks to Home Assistant; the deciding happens in allocator.py."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .allocator import Consumer, allocate, budget_from, unused
from .const import (
    CONF_GRID_EXPORT_IS_NEGATIVE,
    CONF_GRID_SENSOR,
    CONF_INTERVAL,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_NUMBER_ENTITY,
    CONF_POWER_MAX,
    CONF_POWER_MIN,
    CONF_PRIORITY,
    CONF_RESERVE,
    CONF_SWITCH_ENTITY,
    DEFAULT_EXPORT_IS_NEGATIVE,
    DEFAULT_INTERVAL,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_PRIORITY,
    DEFAULT_RESERVE,
    DOMAIN,
    SUBENTRY_TYPE_CONSUMER,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumerState:
    """Runtime state we keep between cycles."""

    subentry_id: str
    name: str
    allocated: float = 0.0
    managed: bool = True
    last_change: object = None
    reason: str = "idle"


@dataclass
class RouterData:
    """Snapshot handed to the entities."""

    surplus: float = 0.0
    budget: float = 0.0
    unused: float = 0.0
    consumers: dict[str, ConsumerState] = field(default_factory=dict)


class SolarRouterCoordinator(DataUpdateCoordinator[RouterData]):
    """Reads the grid sensor, asks the allocator, applies the outcome."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=int(
                    entry.options.get(
                        CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
                    )
                )
            ),
        )
        self._states: dict[str, ConsumerState] = {}

    # ------------------------------------------------------------------ reading

    def _option(self, key: str, default):
        """Options win over data, so reconfiguring takes effect."""
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _numeric(self, entity_id: str | None) -> float | None:
        """Read an entity as a number, normalising kW to W."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        if unit in ("kw", "kilowatt"):
            value *= 1000
        return value

    def _read_grid(self) -> float | None:
        """Grid power in watts, positive meaning export."""
        value = self._numeric(self._option(CONF_GRID_SENSOR, None))
        if value is None:
            return None
        if self._option(CONF_GRID_EXPORT_IS_NEGATIVE, DEFAULT_EXPORT_IS_NEGATIVE):
            value = -value
        return value

    def _subentries(self) -> list[ConfigSubentry]:
        return [
            s
            for s in self.entry.subentries.values()
            if s.subentry_type == SUBENTRY_TYPE_CONSUMER
        ]

    def state_for(self, subentry_id: str, name: str = "") -> ConsumerState:
        if subentry_id not in self._states:
            self._states[subentry_id] = ConsumerState(subentry_id, name)
        return self._states[subentry_id]

    def _held(self, state: ConsumerState, seconds: int) -> bool:
        """Still inside the minimum on/off window."""
        if state.last_change is None or seconds <= 0:
            return False
        return (dt_util.utcnow() - state.last_change).total_seconds() < seconds

    def _switch_is_on(self, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        return st is not None and st.state == "on"

    # ------------------------------------------------------------------ applying

    async def _set_number(self, entity_id: str, value: float) -> None:
        await self.hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": round(value)}, blocking=False
        )

    async def _set_switch(self, entity_id: str, on: bool) -> None:
        await self.hass.services.async_call(
            "switch", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=False
        )

    # ------------------------------------------------------------------ one cycle

    async def _async_update_data(self) -> RouterData:
        grid = self._read_grid()
        if grid is None:
            # No usable reading: change nothing rather than guess.
            return RouterData(consumers=dict(self._states))

        subs = {s.subentry_id: s for s in self._subentries()}

        consumers: list[Consumer] = []
        for sid, sub in subs.items():
            cfg = sub.data
            st = self.state_for(sid, cfg.get("name", sub.title))
            st.name = cfg.get("name", sub.title)

            number_entity = cfg.get(CONF_NUMBER_ENTITY)
            switch_entity = cfg.get(CONF_SWITCH_ENTITY)
            on_now = self._switch_is_on(switch_entity)

            # Compare against what the device is really set to, not against our
            # own bookkeeping. After a restart those disagree, and trusting the
            # bookkeeping would leave a device running that should be off.
            actual = self._numeric(number_entity)
            if actual is None:
                actual = st.allocated

            hold = int(
                cfg.get(CONF_MIN_ON, DEFAULT_MIN_ON)
                if on_now
                else cfg.get(CONF_MIN_OFF, DEFAULT_MIN_OFF)
            )

            consumers.append(
                Consumer(
                    key=sid,
                    priority=int(cfg.get(CONF_PRIORITY, DEFAULT_PRIORITY)),
                    power_min=float(cfg.get(CONF_POWER_MIN, 0)),
                    power_max=float(cfg.get(CONF_POWER_MAX, 0)),
                    has_number=bool(number_entity),
                    has_switch=bool(switch_entity),
                    managed=st.managed,
                    currently_on=on_now,
                    allocated=actual,
                    held=self._held(st, hold),
                )
            )

        already = sum(s.allocated for s in self._states.values() if s.managed)
        budget = budget_from(grid, already, float(self._option(CONF_RESERVE, DEFAULT_RESERVE)))

        decisions = allocate(budget, consumers)

        data = RouterData(surplus=grid, budget=budget)
        for d in decisions:
            sub = subs.get(d.key)
            if sub is None:
                continue
            cfg = sub.data
            st = self.state_for(d.key)

            if d.number_value is not None and cfg.get(CONF_NUMBER_ENTITY):
                await self._set_number(cfg[CONF_NUMBER_ENTITY], d.number_value)
                st.last_change = dt_util.utcnow()

            if d.switch_on is not None and cfg.get(CONF_SWITCH_ENTITY):
                await self._set_switch(cfg[CONF_SWITCH_ENTITY], d.switch_on)
                st.last_change = dt_util.utcnow()

            st.allocated = d.allocated
            st.reason = d.reason
            data.consumers[d.key] = st

        data.unused = unused(budget, decisions)
        return data

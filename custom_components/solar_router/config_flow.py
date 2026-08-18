"""Config and subentry flows for Solar Router."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_GRID_EXPORT_IS_NEGATIVE,
    CONF_GRID_SENSOR,
    CONF_INTERVAL,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_NAME,
    CONF_NUMBER_ENTITY,
    CONF_POWER_MAX,
    CONF_POWER_SENSOR,
    CONF_POWER_MIN,
    CONF_PRIORITY,
    CONF_RESERVE,
    CONF_SETTLE,
    CONF_SWITCH_ENTITY,
    DEFAULT_EXPORT_IS_NEGATIVE,
    DEFAULT_INTERVAL,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_PRIORITY,
    DEFAULT_RESERVE,
    DEFAULT_SETTLE,
    DOMAIN,
    SUBENTRY_TYPE_CONSUMER,
)


def _hub_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_GRID_SENSOR, default=d.get(CONF_GRID_SENSOR)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Required(
                CONF_GRID_EXPORT_IS_NEGATIVE,
                default=d.get(CONF_GRID_EXPORT_IS_NEGATIVE, DEFAULT_EXPORT_IS_NEGATIVE),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RESERVE, default=d.get(CONF_RESERVE, DEFAULT_RESERVE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5000, step=50, unit_of_measurement="W", mode="box"
                )
            ),
            vol.Required(
                CONF_INTERVAL, default=d.get(CONF_INTERVAL, DEFAULT_INTERVAL)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=600, step=5, unit_of_measurement="s", mode="box"
                )
            ),
            vol.Required(
                CONF_SETTLE, default=d.get(CONF_SETTLE, DEFAULT_SETTLE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=600, step=5, unit_of_measurement="s", mode="box"
                )
            ),
        }
    )


class SolarRouterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the router itself."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the grid sensor."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Solar Router", data=user_input)

        return self.async_show_form(step_id="user", data_schema=_hub_schema())

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """This is what puts the + button in the UI."""
        return {SUBENTRY_TYPE_CONSUMER: ConsumerSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SolarRouterOptionsFlow()


class SolarRouterOptionsFlow(OptionsFlow):
    """Change the hub settings after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_hub_schema(current))


class ConsumerSubentryFlow(ConfigSubentryFlow):
    """Add or edit one consumer."""

    def _schema(self, defaults: dict[str, Any] | None = None) -> vol.Schema:
        d = defaults or {}
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): str,
                vol.Optional(
                    CONF_NUMBER_ENTITY, default=d.get(CONF_NUMBER_ENTITY)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(
                    CONF_SWITCH_ENTITY, default=d.get(CONF_SWITCH_ENTITY)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    CONF_POWER_SENSOR, default=d.get(CONF_POWER_SENSOR)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Required(
                    CONF_POWER_MIN, default=d.get(CONF_POWER_MIN, 0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=20000, step=10, unit_of_measurement="W", mode="box"
                    )
                ),
                vol.Required(
                    CONF_POWER_MAX, default=d.get(CONF_POWER_MAX, 1000)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=20000, step=10, unit_of_measurement="W", mode="box"
                    )
                ),
                vol.Required(
                    CONF_PRIORITY, default=d.get(CONF_PRIORITY, DEFAULT_PRIORITY)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=1, mode="box")
                ),
                vol.Required(
                    CONF_MIN_ON, default=d.get(CONF_MIN_ON, DEFAULT_MIN_ON)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=7200, step=30, unit_of_measurement="s", mode="box"
                    )
                ),
                vol.Required(
                    CONF_MIN_OFF, default=d.get(CONF_MIN_OFF, DEFAULT_MIN_OFF)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=7200, step=30, unit_of_measurement="s", mode="box"
                    )
                ),
            }
        )

    def _validate(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Fill in what you have; the mode follows from that.

        A dial alone is fine (zero means off), a switch alone is fine, and both
        together means the switch gates it while the dial sets how hard it runs.
        """
        errors: dict[str, str] = {}

        if not user_input.get(CONF_NUMBER_ENTITY) and not user_input.get(
            CONF_SWITCH_ENTITY
        ):
            errors["base"] = "need_one_entity"

        if user_input[CONF_POWER_MAX] < user_input[CONF_POWER_MIN]:
            errors[CONF_POWER_MAX] = "max_below_min"

        if not user_input[CONF_POWER_MAX]:
            errors[CONF_POWER_MAX] = "max_required"

        return errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a consumer."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=self._schema(user_input), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing consumer."""
        subentry = self._get_reconfigure_subentry()

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema(user_input or dict(subentry.data)),
            errors=errors,
        )

"""Tests for the allocation logic.

Run with:  python -m pytest tests/ -q
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "solar_router")
)

from allocator import Consumer, allocate, budget_from, unused


def by_key(decisions):
    return {d.key: d for d in decisions}


def dial(key, priority=10, pmin=0, pmax=3000, **kw):
    """A consumer with only a number entity."""
    return Consumer(key, priority, pmin, pmax, has_number=True, **kw)


def relay(key, priority=10, rated=2300, **kw):
    """A consumer with only a switch."""
    return Consumer(key, priority, 0, rated, has_switch=True, **kw)


def both(key, priority=10, pmin=0, pmax=3000, **kw):
    """A consumer with a switch and a dial."""
    return Consumer(key, priority, pmin, pmax, has_number=True, has_switch=True, **kw)


# --------------------------------------------------------------- budget


def test_budget_adds_back_own_draw():
    """The whole point: our own consumption must not look like a shortage."""
    assert budget_from(grid_export=200, already_allocated=1000, reserve=0) == 1200


def test_budget_honours_reserve():
    assert budget_from(grid_export=1000, already_allocated=0, reserve=300) == 700


def test_budget_can_go_negative_when_importing():
    assert budget_from(grid_export=-500, already_allocated=0, reserve=0) == -500


# --------------------------------------------------------------- dial only


def test_dial_takes_what_fits():
    d = by_key(allocate(1500, [dial("boiler", pmin=200)]))["boiler"]
    assert d.allocated == 1500
    assert d.number_value == 1500


def test_dial_capped_at_max():
    assert by_key(allocate(5000, [dial("boiler")]))["boiler"].allocated == 3000


def test_dial_off_below_its_minimum():
    """Zero is off; that is why a dial needs no switch."""
    # allocated is what the device is actually set to right now.
    d = by_key(allocate(150, [dial("boiler", pmin=200, allocated=1500)]))["boiler"]
    assert d.allocated == 0
    assert d.number_value == 0  # actively dialled down
    assert d.reason == "below minimum"


def test_dial_already_at_zero_is_left_alone():
    d = by_key(allocate(150, [dial("boiler", pmin=200, allocated=0)]))["boiler"]
    assert d.allocated == 0
    assert d.number_value is None  # nothing to do


def test_dial_not_written_when_unchanged():
    d = by_key(allocate(1500, [dial("boiler", allocated=1500)]))["boiler"]
    assert d.allocated == 1500
    assert d.number_value is None  # no pointless service call


def test_priority_order_is_respected():
    got = by_key(
        allocate(4000, [dial("miner", priority=20), dial("boiler", priority=10)])
    )
    assert got["boiler"].allocated == 3000
    assert got["miner"].allocated == 1000


# --------------------------------------------------------------- switch only


def test_relay_turns_on_when_it_fits():
    d = by_key(allocate(2500, [relay("car")]))["car"]
    assert d.switch_on is True
    assert d.allocated == 2300


def test_relay_stays_off_when_it_does_not_fit():
    d = by_key(allocate(1000, [relay("car")]))["car"]
    assert d.switch_on is None
    assert d.allocated == 0


def test_running_relay_stays_on_while_budget_holds():
    d = by_key(allocate(2300, [relay("car", currently_on=True)]))["car"]
    assert d.switch_on is None
    assert d.allocated == 2300


def test_running_relay_goes_off_on_shortfall():
    d = by_key(allocate(-400, [relay("car", currently_on=True)]))["car"]
    assert d.switch_on is False


def test_minimum_on_time_keeps_it_running():
    d = by_key(allocate(-400, [relay("car", currently_on=True, held=True)]))["car"]
    assert d.switch_on is None
    assert d.reason == "held on"


def test_minimum_off_time_prevents_restart():
    d = by_key(allocate(5000, [relay("car", held=True)]))["car"]
    assert d.switch_on is None
    assert d.reason == "held off"


# --------------------------------------------------------------- switch + dial


def test_both_switches_on_and_dials_up():
    d = by_key(allocate(2000, [both("charger", pmin=1400, pmax=7400)]))["charger"]
    assert d.switch_on is True
    assert d.number_value == 2000
    assert d.allocated == 2000


def test_both_switches_off_below_minimum():
    d = by_key(
        allocate(600, [both("charger", pmin=1400, pmax=7400, currently_on=True)])
    )["charger"]
    assert d.switch_on is False
    assert d.allocated == 0


def test_both_leaves_switch_alone_when_already_correct():
    d = by_key(allocate(2000, [both("charger", pmin=1400, currently_on=True)]))[
        "charger"
    ]
    assert d.switch_on is None  # already on
    assert d.number_value == 2000


def test_both_respects_minimum_off_time():
    """Cannot start yet, so it must not claim the power either."""
    c = both("charger", pmin=1400, pmax=7400, held=True)
    d = by_key(allocate(3000, [c]))["charger"]
    assert d.switch_on is None
    assert d.allocated == 0
    assert d.reason == "held off"


def test_held_charger_does_not_starve_the_next_one():
    charger = both("charger", priority=10, pmin=1400, pmax=7400, held=True)
    boiler = dial("boiler", priority=20, pmax=3000)
    got = by_key(allocate(3000, [charger, boiler]))
    assert got["charger"].allocated == 0
    assert got["boiler"].allocated == 3000  # power was handed on


# --------------------------------------------------------------- misc


def test_unmanaged_is_skipped_and_keeps_its_budget():
    got = by_key(
        allocate(
            2000,
            [dial("miner", priority=10, managed=False), dial("boiler", priority=20)],
        )
    )
    assert got["miner"].allocated == 0
    assert got["boiler"].allocated == 2000


def test_unused_is_what_nobody_took():
    decisions = allocate(2500, [dial("boiler", pmax=1000)])
    assert unused(2500, decisions) == 1500


def test_no_consumers_leaves_everything_unused():
    assert unused(1000, allocate(1000, [])) == 1000


def test_mixed_fleet_realistic():
    """Boiler on a dial, car on a relay, miner on a dial. 4 kW surplus."""
    got = by_key(
        allocate(
            4000,
            [
                dial("boiler", priority=10, pmin=200, pmax=3000),
                relay("car", priority=20, rated=2300),
                dial("miner", priority=30, pmin=500, pmax=5000),
            ],
        )
    )
    assert got["boiler"].allocated == 3000
    assert got["car"].allocated == 0  # 1000 left, needs 2300
    assert got["miner"].allocated == 1000


# --------------------------------------------------------------- measured draw


def test_saturated_boiler_hands_its_power_on():
    """Bart's case: boiler allowed 3 kW, but its own thermostat cut out.

    Without measuring we would count 3 kW as spent, see the export rise, and
    hand out that same 3 kW a second time.
    """
    boiler = dial(
        "boiler", priority=10, pmin=200, pmax=3000, allocated=3000, measured=0
    )
    car = relay("car", priority=20, rated=2300)

    got = by_key(allocate(3000, [boiler, car]))
    assert got["boiler"].claim == 0  # costs us nothing right now
    assert got["boiler"].number_value is None  # dial stays up, ready to resume
    assert got["boiler"].reason == "allowed, not drawing"
    assert got["car"].switch_on is True  # the power went somewhere useful


def test_drawing_boiler_keeps_its_claim():
    boiler = dial(
        "boiler", priority=10, pmin=200, pmax=3000, allocated=3000, measured=3000
    )
    car = relay("car", priority=20, rated=2300)

    got = by_key(allocate(3000, [boiler, car]))
    assert got["boiler"].claim == 3000
    assert got["car"].switch_on is None  # nothing left over


def test_partial_draw_only_claims_what_it_uses():
    boiler = dial(
        "boiler", priority=10, pmin=200, pmax=3000, allocated=3000, measured=1200
    )
    got = by_key(allocate(3000, [boiler]))
    assert got["boiler"].claim == 1200
    assert unused(3000, [got["boiler"]]) == 1800


def test_claim_never_exceeds_what_we_allowed():
    """A device drawing more than we gave it is not our budget to spend."""
    boiler = dial("boiler", priority=10, pmax=1000, allocated=1000, measured=2500)
    assert by_key(allocate(1000, [boiler]))["boiler"].claim == 1000


def test_without_a_sensor_we_assume_it_uses_its_allocation():
    boiler = dial("boiler", priority=10, pmin=200, pmax=3000, allocated=3000)
    assert by_key(allocate(3000, [boiler]))["boiler"].claim == 3000


def test_saturated_relay_also_releases_its_power():
    """A switched load that is on but idle, e.g. a charger that finished."""
    car = relay("car", priority=10, rated=2300, currently_on=True, measured=0)
    boiler = dial("boiler", priority=20, pmin=200, pmax=3000)
    got = by_key(allocate(2300, [car, boiler]))
    assert got["car"].claim == 0
    assert got["car"].switch_on is None  # left on; it may resume by itself
    assert got["boiler"].allocated == 2300


# --------------------------------------------------------------- priority vs fit


def test_lower_priority_dial_soaks_up_what_the_relay_cannot_use():
    """Car has priority but needs 2 kW in one go; only 1 kW is available.

    The boiler is allowed to take it rather than exporting it, because the car
    cannot use a partial amount anyway.
    """
    car = relay("car", priority=10, rated=2000)
    boiler = dial("boiler", priority=20, pmax=3000)

    got = by_key(allocate(1000, [car, boiler]))
    assert got["car"].claim == 0
    assert got["car"].reason == "waiting for surplus"
    assert got["boiler"].allocated == 1000  # nothing exported


def test_relay_takes_over_once_it_fits():
    """With 2 kW the car wins on priority and the boiler is dialled back."""
    car = relay("car", priority=10, rated=2000)
    boiler = dial("boiler", priority=20, pmax=3000, allocated=1000, measured=1000)

    # boiler drawing 1 kW, exporting 1 kW -> 2 kW to spend
    budget = budget_from(grid_export=1000, already_allocated=1000, reserve=0)
    got = by_key(allocate(budget, [car, boiler]))

    assert got["car"].switch_on is True
    assert got["boiler"].number_value == 0  # gives way to the higher priority


# --------------------------------------------------------------- dead time

from allocator import should_settle


def test_no_wait_before_we_have_ever_acted():
    assert should_settle(grid_updated_at=100, last_action_at=None, now=200) is False


def test_wait_while_the_meter_still_predates_our_action():
    """Meter last spoke at t=100, we acted at t=110. It has not seen us yet."""
    assert should_settle(grid_updated_at=100, last_action_at=110, now=120) is True


def test_go_ahead_once_the_meter_has_caught_up():
    assert should_settle(grid_updated_at=140, last_action_at=110, now=150) is False


def test_a_reading_exactly_at_the_action_is_not_new_enough():
    assert should_settle(grid_updated_at=110, last_action_at=110, now=120) is True


def test_settle_margin_holds_us_even_with_a_fresh_reading():
    """For devices that need a moment before their draw shows up."""
    assert (
        should_settle(grid_updated_at=140, last_action_at=110, now=115, settle=30)
        is True
    )
    assert (
        should_settle(grid_updated_at=140, last_action_at=110, now=145, settle=30)
        is False
    )


def test_missing_meter_timestamp_means_wait():
    assert should_settle(grid_updated_at=None, last_action_at=110, now=200) is True


# --------------------------------------------------------- modulerend regelen


def test_jumps_straight_to_the_target():
    """Geen demping meer: wat het budget toelaat wordt meteen geschreven."""
    d = by_key(allocate(3000, [dial("boiler", pmax=3000, allocated=0)]))["boiler"]
    assert d.allocated == 3000


def test_comes_straight_down_too():
    d = by_key(allocate(1000, [dial("boiler", pmax=3000, allocated=3000)]))["boiler"]
    assert d.allocated == 1000


def test_at_least_the_minimum_once_it_fits():
    d = by_key(allocate(900, [dial("boiler", pmin=800, pmax=3000, allocated=0)]))[
        "boiler"
    ]
    assert d.allocated == 900


def test_target_below_minimum_switches_off():
    """Onder het minimum is uit ook echt uit, niet het minimum aanhouden."""
    d = by_key(allocate(300, [dial("boiler", pmin=800, pmax=3000, allocated=3000)]))[
        "boiler"
    ]
    assert d.allocated == 0


# --------------------------------------------------------------- dode zone


def test_dead_zone_scales_with_the_maximum():
    """1% van het maximum, dus 30 W bij een boiler van 3 kW."""
    assert (
        by_key(allocate(25, [dial("boiler", pmax=3000, allocated=0)]))[
            "boiler"
        ].allocated
        == 0
    )
    assert (
        by_key(allocate(40, [dial("boiler", pmax=3000, allocated=0)]))[
            "boiler"
        ].allocated
        == 40
    )


def test_small_device_keeps_a_sane_floor():
    """Bij een klein apparaat blijft de dode zone 10 W, niet 1 W."""
    assert (
        by_key(allocate(8, [dial("pomp", pmax=100, allocated=0)]))["pomp"].allocated
        == 0
    )
    assert (
        by_key(allocate(16, [dial("pomp", pmax=100, allocated=0)]))["pomp"].allocated
        == 16
    )


def test_normal_values_are_untouched_by_the_dead_zone():
    d = by_key(allocate(2000, [dial("boiler", pmax=3000, allocated=0)]))["boiler"]
    assert d.allocated == 2000


# --------------------------------------------------------------- phase limit
# 30 sep 2026: de auto (2100 W, L2) werd binnen zijn minimale aan-tijd
# vastgehouden terwijl de huurder op dezelfde fase kookte, en L2 trok 26 A op
# een zekering van 25 A. Bart zette hem met de hand uit.


def test_phase_over_limit_switches_off_even_when_held():
    car = relay("car", rated=2100, currently_on=True, held=True,
                phase_current=26, phase_limit=25)
    d = by_key(allocate(5000, [car]))["car"]
    assert d.switch_on is False
    assert d.reason == "phase limit"
    assert d.claim == 0


def test_phase_without_room_does_not_start():
    # 17 A op de fase zonder de auto, plus 9,1 A voor de auto = boven 25 A
    car = relay("car", rated=2100, phase_current=17, phase_limit=25)
    d = by_key(allocate(5000, [car]))["car"]
    assert d.switch_on is None
    assert d.reason == "phase limit"


def test_phase_with_room_starts_as_usual():
    car = relay("car", rated=2100, phase_current=10, phase_limit=25)
    d = by_key(allocate(5000, [car]))["car"]
    assert d.switch_on is True


def test_own_draw_does_not_count_against_itself():
    # 24 A inclusief de eigen 9,1 A: onder de grens, dus gewoon aan laten
    car = relay("car", rated=2100, currently_on=True, measured=2100,
                phase_current=24, phase_limit=25)
    d = by_key(allocate(5000, [car]))["car"]
    assert d.switch_on is None
    assert d.allocated == 2100


def test_phase_caps_a_dial():
    # 20 A van anderen laat 5 A = 1150 W over voor een modulerende boiler
    boiler = dial("boiler", pmax=3000, phase_current=20, phase_limit=25)
    d = by_key(allocate(5000, [boiler]))["boiler"]
    assert d.allocated == 5 * 230


def test_no_phase_sensor_means_no_limit():
    car = relay("car", rated=2100, currently_on=True, held=True)
    d = by_key(allocate(-3000, [car]))["car"]
    assert d.reason == "held on"

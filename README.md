# Solar Router

[![hacs][hacs-badge]][hacs-url]
[![release][release-badge]][release-url]
[![license][license-badge]](LICENSE)

Spend your own solar power instead of exporting it.

You tell it which sensor reports your grid power, then add consumers — a boiler,
a car charger, a heat pump, a miner. Each gets a priority. Every cycle the
integration works out how much surplus there is and hands it out, top priority
first. Devices with an adjustable power setting are dialled to whatever fits;
on/off devices are switched when their full draw fits.

This is deliberately reactive, not predictive. It does not forecast the weather
or optimise against energy prices — it looks at what is happening right now and
divides it up. If you need forecasting, look at EMHASS instead.

## Requirements

Home Assistant **2025.3.0** or newer. Consumers are config subentries, and those
did not exist before that release.

## Install

### HACS

This is not in the default HACS store. Add it as a custom repository:

1. HACS → three dots, top right → **Custom repositories**
2. Repository `brtwrs/solar-router`, type **Integration**
3. Find **Solar Router** in HACS, install it, restart Home Assistant

### By hand

Copy `custom_components/solar_router` into your Home Assistant `config`
directory and restart.

Either way, finish with **Settings → Devices & Services → Add integration →
Solar Router**.

## Setting it up

**The hub** asks for one thing that matters: the sensor reporting grid power.
Tell it whether export shows as a negative number (usually yes). Optionally keep
a reserve in watts as a buffer, and set how often to recalculate.

**Consumers** are added with the `+` on the integration page. Per consumer:

| Field | Meaning |
|---|---|
| How is it controlled | An adjustable `number` entity, or an on/off `switch` |
| Minimum power | Below this it is not worth running. On/off devices: leave at 0 |
| Maximum power | The ceiling. For on/off: what it draws when running |
| Priority | Lower number is served first |
| Minimum on/off time | Keeps relays from chattering |

Each consumer gets a device with two entities: the power currently routed to it,
and a **Managed** switch to take it out of the routing when you want to run it
by hand.

## How the surplus is worked out

The one thing worth understanding:

```
budget = current export + what our own consumers already draw − reserve
```

Adding back your own draw is essential. Without it, switching the boiler on
makes the export disappear, which looks like a shortage, which switches the
boiler off again — and round it goes. With it, the budget stays stable and each
consumer simply holds its share.

## What it works with

Anything Home Assistant already exposes. There is no device support to speak of,
because the integration never talks to hardware — it drives entities:

- **Modulating consumers**: any `number` entity that sets a power level. A
  hot-water boiler with an adjustable element, a wallbox with a current setting.
- **On/off consumers**: any `switch` entity. A pump, a plug, an immersion heater.
- **Both**: a device with a switch *and* a level gets switched on when its
  minimum fits, then dialled from there.
- **Optionally a power sensor** per consumer. With one, the router accounts for
  what a device actually draws instead of what it was told to draw — worth
  adding for anything that does not obey immediately.

## When the numbers update

Every cycle the integration reads the grid sensor, works out the budget, and
writes new setpoints. The cycle length is yours to pick (default 30 s). Two
things hold it back on purpose:

- It waits for a grid reading that is genuinely newer than its last action.
  Deciding twice on the same measurement is how a controller overshoots.
- The settle time adds a further margin for devices that take a moment before
  their draw shows up.

If the grid sensor goes unavailable or stops reporting a number, the entities go
unavailable and **nothing is changed** — consumers keep their last setpoint
rather than being driven on a guess.

## A worked example

A 10 kW roof, a boiler with an adjustable element, and a car charger. The boiler
comes first because a kilowatt-hour of hot water is worth more than a slow
charge, and it can take any amount rather than all-or-nothing.

**Hub**

| Setting | Value |
|---|---|
| Grid power sensor | `sensor.grid_net_power` |
| Export is negative | on |
| Keep in reserve | 0 W |
| Recalculate every | 15 s |
| Settle time | 15 s |
| Adjustment speed | 1.0 |

**Consumer: boiler**

| Setting | Value |
|---|---|
| Number entity | `number.boiler_power` |
| Minimum / maximum power | 0 W / 3000 W |
| Priority | 50 |
| Minimum on/off time | 0 s / 0 s |

**Consumer: car**

| Setting | Value |
|---|---|
| Switch entity | `switch.car_plug` |
| Minimum / maximum power | 0 W / 2100 W |
| Priority | 45 |
| Minimum on/off time | 300 s / 300 s |

The car has the *lower* priority number, so it is served first — it needs its
full 2100 W or nothing, while the boiler happily takes whatever is left over.
The 300 s minimum on and off keep the plug from chattering on a cloudy day; the
boiler needs no such protection because dialling it costs nothing.

Set the settle time from your own meter. A P1 meter that refreshes every 10 s
and a boiler that responds in about 1.5 s means roughly 11 s of dead time, so
15 s is a sober choice. Guessing high just makes it sluggish.

## What people use it for

- Dumping midday surplus into a hot-water boiler instead of exporting it.
- Charging a car only on what the roof is making, with the boiler taking
  priority because heat is worth more per kilowatt-hour than a slow charge.
- Running something optional — a dehumidifier, a pool pump, a miner — on the
  tail end of the surplus, with a low priority so it only gets leftovers.

## Known limitations

- **Reactive, not predictive.** No weather forecast, no price optimisation. If
  you need those, look at EMHASS.
- **An on/off consumer only starts when its full draw fits.** With 1900 W of
  surplus and a 2100 W charger, nothing happens and the surplus is exported.
- **One hub per Home Assistant.** The integration allows a single config entry,
  since it reasons about one grid connection.
- **Consumer state is not kept over a restart.** The Managed switches go back on
  and timers start fresh, though the router reads what devices are actually set
  to rather than trusting its own bookkeeping.
- **No battery support yet.** A battery is not just another consumer; it has a
  charge level, a ceiling, and round-trip losses.

## When it is not doing what you expect

Start with the hub sensor's attributes. `budget`, `unused`, `settling` and the
per-consumer `allocations` show exactly what the last cycle decided and why.

| What you see | Usually means |
|---|---|
| Entities unavailable | The grid sensor is unavailable or not numeric. The log says which. |
| `settling: true` and nothing moving | Waiting for a fresher meter reading. Lower the settle time, or accept that your meter is slow. |
| A consumer stuck at `held on` / `held off` | Its minimum on/off time has not elapsed. |
| Surplus available but an on/off device idle | Its full draw does not fit in what is left. |
| Everything oscillating | Lower the gain. 1.0 jumps straight to the target, which overshoots when the meter lags. |

For a bug report, use **Settings → Devices & Services → Solar Router → three
dots → Download diagnostics**. That includes the config, the last cycle, and
what every source entity read at that moment.

## Removing it

**Settings → Devices & Services → Solar Router → three dots → Delete.** That
removes the hub, its consumers and all their entities. Nothing is left behind in
Home Assistant, and the entities the router was driving keep whatever value they
last had — check your boiler or charger afterwards if that matters.

Installed through HACS? Remove it there too, then restart.

## Tests

The allocation logic lives in `allocator.py` and has no Home Assistant imports,
so it can be tested on its own:

```bash
python -m pytest tests/ -q
```

## Status

Version 0.1.0, a first release. Written and run against Home Assistant 2026.8;
the 2025.3.0 floor is where the APIs it uses first appeared, not a version it has
been tested on.

## License

MIT — see [LICENSE](LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-custom-41BDF5.svg
[hacs-url]: https://hacs.xyz/
[release-badge]: https://img.shields.io/github/v/release/brtwrs/solar-router
[release-url]: https://github.com/brtwrs/solar-router/releases
[license-badge]: https://img.shields.io/github/license/brtwrs/solar-router

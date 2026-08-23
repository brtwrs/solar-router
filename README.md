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
2. Repository `bartwijers/solar-router`, type **Integration**
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
[release-badge]: https://img.shields.io/github/v/release/bartwijers/solar-router
[release-url]: https://github.com/bartwijers/solar-router/releases
[license-badge]: https://img.shields.io/github/license/bartwijers/solar-router

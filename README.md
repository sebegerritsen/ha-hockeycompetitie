# KNHB Hockey for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) integration, installable through [HACS](https://hacs.xyz/),
for Dutch field and indoor hockey: the fixtures, results and standings of any team of any KNHB club.

> **Status: early development.** Nothing to install yet. The data source has been investigated and
> works (see [docs/api.md](docs/api.md)); the integration itself is being built. Contributions welcome,
> see [Contributing](#contributing).

## What it will do

Pick your club and team in the Home Assistant UI (no account needed). Per team you get:

- **A calendar** with every match: opponent, home or away, venue and address, pitch, and the score
  once it has been played. Use it in your dashboards or automations like any other calendar.
- **Sensors**
  - *Next match*: start time, with opponent, home/away, venue, pitch and competition as attributes.
  - *Last result*: score, with win/draw/loss.
  - *Standing*: rank in the pool, with points, played, goals for and against.
- Field (veld) and indoor (zaal) teams alike; add one entry per team, for example a child's field
  team and indoor team.

## Data source

The same public match data that powers the match centre on [hockey.nl](https://www.hockey.nl/match-center),
operated by the KNHB (Koninklijke Nederlandse Hockey Bond). It covers all ±350 clubs, regardless of
which club administration software (LISA, AllUnited, …) a club uses. No login is required.

This project is **not affiliated with or endorsed by the KNHB**. The API is not officially documented;
it is described in [docs/api.md](docs/api.md) as far as we understand it. The integration polls
gently (every 30 minutes, more often on match days) and caches what it can. If the KNHB asks us to
change or stop something, we will.

## Installation

Not released yet. Once it is: HACS → Integrations → ⋮ → Custom repositories → add this repository
as *Integration*, install **KNHB Hockey**, restart Home Assistant, then *Settings → Devices & services →
Add integration → KNHB Hockey*.

## Contributing

Issues and pull requests are welcome, in English or Dutch.

- Read [docs/api.md](docs/api.md) for how the data source works.
- [tools/probe.py](tools/probe.py) is a small standalone script to explore the API from the command line
  (`python3 tools/probe.py /clubs`), without Home Assistant.
- Planned work is tracked in the [issues](../../issues).

Please don't commit personal data (names, team rosters of real people, tokens) in examples or tests;
use made-up or anonymised data.

## License

[MIT](LICENSE)

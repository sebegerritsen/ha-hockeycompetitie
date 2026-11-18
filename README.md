# Hockeycompetitie for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) integration, installable through [HACS](https://hacs.xyz/),
for Dutch field and indoor hockey: the fixtures, results and standings of any team of any KNHB club.

> **Status: early development (v0.1.0).** It works and is in use, but expect changes. Feedback welcome,
> see [Contributing](#contributing).

## What it does

Pick your club and team in the Home Assistant UI (no account needed). Per team you get a device with:

| Entity | State | Details (attributes) |
|---|---|---|
| **Calendar** (named after the team) | on during a match | every match of the season: opponent, venue and address, pitch, competition, and the score once played |
| **Next match** | kick-off time | opponent (with logo, rank, points and recent form), home or away, venue, address, pitch, meet time, the previous meeting with this opponent, and the matches after it |
| **Next opponent** | the opponent's name (with their logo) | home or away, kick-off, venue, their rank, points and form |
| **Home or away** | home or away | the details of the next match |
| **Meet time** | when the team meets | kick-off minus 30 minutes, or what you set in the options (home and away separately) |
| **Match today** | on all day on match days | kick-off, meet time, opponent, venue |
| **Match update** (event) | fires on a change | *cancelled*, *back on*, *rescheduled*, *venue or pitch changed*, *result*, with the details of the match |
| **Weather at next match** | temperature | the KNHB's forecast for the match: chance of rain, feels-like temperature, a rating and a short (Dutch) description; from 48 hours before |
| **Last result** | win, draw or loss | score, goals for and against, opponent, home or away |
| **Standing** | rank in the pool | points, played, won/drawn/lost, goals, goal difference, form (last 5), and the whole table |

- Field (veld) and indoor (zaal) teams alike; add one entry per team, for example a child's field
  team and indoor team.
- Matches of the team's other pools this season (cup rounds, an earlier period) are in the calendar
  too, as far as the KNHB publishes them.
- Change alerts also catch what changed while Home Assistant was off: the integration remembers
  the matches as it last saw them.
- Cancelled matches are left out of the calendar, as Home Assistant expects of calendars, so that
  automations on the calendar don't fire for them. The *Match update* entity reports the cancellation.
- Matches have no end time in the KNHB data; calendar events last 90 minutes, or 60 minutes for
  indoor hockey and the youngest age groups (*Jongste jeugd*).
- The youngest age groups have no standings, so their *Standing* sensor stays unknown.
- Dutch and English.

### Options

*Settings → Devices & services → Hockeycompetitie → (team) → Configure*: when the team meets, in minutes
before kick-off, for home and away matches (default 30). Travel time is not included.

### Blueprints

Ready-made automations that send a notification to your phone (Home Assistant app), in Dutch or English:

| Blueprint | What it does | |
|---|---|---|
| Notify on match changes | a match is cancelled, back on, moved, or has a result | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebegerritsen%2Fha-hockeycompetitie%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhockeycompetitie%2Fmatch_update_notify.yaml) |
| Reminder before meet time | a set time before the meet time, with venue, address and weather | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebegerritsen%2Fha-hockeycompetitie%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhockeycompetitie%2Fmeet_time_reminder.yaml) |
| Match day summary | at a set time on match days: opponent, kick-off, meet time, venue, weather | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebegerritsen%2Fha-hockeycompetitie%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhockeycompetitie%2Fmatch_day_summary.yaml) |

## Data source

The same public match data that powers the match centre on [hockey.nl](https://www.hockey.nl/match-center),
operated by the KNHB (Koninklijke Nederlandse Hockey Bond). It covers all ±350 clubs, regardless of
which club administration software (LISA, AllUnited, …) a club uses. No login is required.

This project is **not affiliated with or endorsed by the KNHB**. The API is not officially documented;
it is described in [docs/api.md](docs/api.md) as far as we understand it. If the KNHB asks us to change
or stop something, we will.

The API allows 5 requests per minute per IP address, shared with everyone on your network who uses
hockey.nl. The integration therefore polls gently: a team's page every 30 minutes, every 5 minutes
around the team's own matches, every 2 hours when there are none coming up, the next match's weather
every 3 hours from 48 hours before, and all teams together never more than 4 requests a minute.

## Installation

Requires Home Assistant 2025.12 or newer.

[![Open your Home Assistant instance and open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sebegerritsen&repository=ha-hockeycompetitie&category=integration)

**HACS** (since Home Assistant 2026.11 part of the built-in *Marketplace*): search for **Hockeycompetitie**
(or use the button above), install it and restart Home Assistant.

If it doesn't show up, add `https://github.com/sebegerritsen/ha-hockeycompetitie` as a custom repository of
type *Integration* first, then install it the same way.

**Manually:** copy `custom_components/hockeycompetitie` into the `custom_components` folder of your Home
Assistant configuration and restart Home Assistant.

Then *Settings → Devices & services → Add integration → Hockeycompetitie*: type part of your club's name or
town, pick the club, pick the team.

## Examples

The next match on a dashboard, with a Markdown card:

```yaml
type: markdown
content: >
  {% set s = 'sensor.hc_example_jo12_1_next_match' %}
  {% if states(s) not in ['unknown', 'unavailable'] %}
  **{{ state_attr(s, 'home_team') }} – {{ state_attr(s, 'away_team') }}**
  {{ as_timestamp(states(s)) | timestamp_custom('%A %d %B, %H:%M') }}
  {{ state_attr(s, 'venue') }}, {{ state_attr(s, 'field') }}
  {% endif %}
```

A notification when a match is cancelled, without the blueprint:

```yaml
triggers:
  - trigger: state
    entity_id: event.hc_example_jo12_1_match_update
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none and trigger.from_state.state != 'unavailable'
         and trigger.to_state.attributes.event_type == 'cancelled' }}
actions:
  - action: notify.notify
    data:
      message: >-
        Cancelled: {{ trigger.to_state.attributes.home_team }} –
        {{ trigger.to_state.attributes.away_team }}
```

## Contributing

Issues and pull requests are welcome, in English or Dutch.

- Read [docs/api.md](docs/api.md) for how the data source works.
- Tests: `pip install -r requirements_test.txt`, then `pytest` (Python 3.14). Lint: `ruff check` and
  `ruff format`.
- [tools/probe.py](tools/probe.py) is a small standalone script to explore the API from the command line
  (`python3 tools/probe.py /clubs`), without Home Assistant.
- Planned work is tracked in the [issues](../../issues).

Please don't commit personal data (names, team rosters of real people, tokens) in examples or tests;
use made-up or anonymised data.

## License

[MIT](LICENSE). The icon is drawn from [Material Design Icons](https://pictogrammers.com/library/mdi/)
(Apache 2.0).

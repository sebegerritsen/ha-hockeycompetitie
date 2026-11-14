# The KNHB match data API

What we know about the API behind the match centre on hockey.nl, found by reading the
match centre's public JavaScript (`https://mc.static-hw.nl/v2/match-center.js` and the chunks it
loads, notably `useApi-*.js`) and by trying it. Not officially documented; it may change. Last
checked: November 2026.

## Base URL and versions

- Base URL: `https://app.hockeyweerelt.nl`
- Every signed request carries `X-HAPI-Version: 8`.
- Responses are JSON, usually `{"data": …}`; team pages add `filters` and `header`.

The older `https://publicaties.hockeyweerelt.nl/mc/…` endpoints that some community projects describe
no longer work (they redirect to themselves).

## Authentication: an anonymous device

No user account is needed. The website registers itself as a device and signs every request.

1. **Register** (unsigned):

   ```
   POST /device/register
   Content-Type: application/json

   {"uuid": "<random UUID v4>", "os": "Web"}
   ```

   Response: `{"token": "<device token>", …}`. Keep the UUID and token; reuse them.

2. **Sign** every other request with four headers:

   | Header | Value |
   |---|---|
   | `X-HAPI-Authorization` | the device token |
   | `X-HAPI-Timestamp` | Unix time in seconds |
   | `X-HAPI-Signature` | `sha1(timestamp + path + query + reverse(uuid))`, lowercase hex |
   | `X-HAPI-Version` | `8` |

   Where:
   - `path` is the URL path with every character outside `[a-zA-Z0-9-/]` removed;
   - `query` is each query parameter as `key=value`, concatenated without separators, with every
     character outside `[a-zA-Z0-9-/=]` removed from key and value (so `filter[dateStart]=2026-11-14`
     becomes `filterdateStart=2026-11-14`); parameters with an empty key are skipped;
   - `reverse(uuid)` is the device UUID string reversed.

3. On **HTTP 401**, register again (new token) and retry once. The website does the same.

## Rate limit and caching

- **5 requests per minute per IP address**, not per device: a second device registered from the
  same address continues the same count. So every team configured in one Home Assistant shares it,
  and so does anyone on the same network browsing hockey.nl. Responses carry
  `x-ratelimit-limit: 5` and `x-ratelimit-remaining`; over the limit the API answers **HTTP 429**
  with `Retry-After` (seconds) and `x-ratelimit-reset` (Unix time).
- `POST /device/register` has its own, looser limit (60 per minute).
- Responses carry `cache-control: max-age=300, private` and the server caches too
  (`x-hapi-cache-hit: 1`), so polling a page more often than every 5 minutes gains nothing.

The integration sends at most 4 requests per minute through one throttle shared by all its config
entries, waits out a short `Retry-After` once, and otherwise tries again later.

A logged-in user adds `Authorization: Bearer <id_token>` from the KNHB login; not needed for public data.

## Endpoints used

| Endpoint | What it returns |
|---|---|
| `GET /clubs` | All clubs: `federation_reference_id` (e.g. `HH11AB1`), `name`, `friendly_name`, `city`, `logo`, `type` (`regular` or `business`). |
| `GET /clubs/{federation_reference_id}` | Club details plus `teams`: `id`, `name`, `short_name` (`JO14-2`, `MO10-Geel`, …), `hockey_type` (`VE` field, `ZA` indoor), `category_group_name` (`Jongste jeugd`, `Junioren`, `Senioren`), `recent_poule_id`. |
| `GET /poules/{poule_id}/teams/{team_id}` | The team page: `data.poules[]`, each with `competition`, `standings[]` and `matches[]` (all matches in that pool, not only the team's own). Use the team's `recent_poule_id`; it changes when a new competition period starts, so refresh it from `/clubs/{id}` now and then. `data` itself describes the competition (`poule_id`, `season_id`, `period_name`, …) and has `neighbors[]`: the team's other pools, this season and earlier ones (see below). |
| `GET /matches/{id}` | One match in detail, adding `weather` (forecast for the match), `actions`, `videos`, `approved_by_home_team` / `approved_by_away_team`. See below. |
| `GET /poules/{poule_id}` | A pool, optionally with `?filter[dateStart]=YYYY-MM-DD&filter[dateEnd]=YYYY-MM-DD`. |
| `GET /facilities`, `GET /facilities/{id}/matches?filter[dateStart]=…&filter[dateEnd]=…` | Venues and the matches played there. |
| `GET /competitions/national`, `GET /competitions/national/{id}` | Competitions. |

## Match object

```json
{
  "id": 2117062,
  "date": "2026-10-31T14:00:00+01:00",
  "status": "final",
  "cancellation_minute": null,
  "home": {"id": 0, "name": "Club A MO18-1", "short_name": "MO18-1", "logo": "…", "federation_reference_id": "…"},
  "away": {"id": 0, "name": "Club B MO18-1", "short_name": "MO18-1", "logo": "…", "federation_reference_id": "…"},
  "score": {"home": 1, "away": 2},
  "shootouts": {"home": 0, "away": 0},
  "location": {
    "facility": {"name": "Sportpark …", "address": "Straat 1\n1234AB Plaats"},
    "field": {"id": 40, "name": "Veld 1", "type": "Waterveld"}
  },
  "remarks": {"official": "", "info": null},
  "competition_name": "…", "competition_category": "Meisjes O18", "competition_period": "Nov tm Jun",
  "competition_season": "2026-2027", "poule_name": "…", "round": 1
}
```

- `status`: the match centre's code (`src/types/api/match.ts`) knows `scheduled`, `announced`,
  `live`, `result`, `final`, `discontinued`, `cancelled`, `expired` and `unknown`. Seen in real data:
  `scheduled`, `final` and `cancelled` (a youngest-youth pool, November 2026). The match centre lists
  `scheduled`, `announced` and `live` as the programme, and `result`, `final`, `unknown` as results;
  `discontinued` and `cancelled` stay in the programme until their date has passed. What exactly
  `announced`, `result` and `expired` mean is not confirmed.
- `score` is `{"home": 0, "away": 0}` for a match that has not been played: only trust it for `live`,
  `result`, `final` and `discontinued`.
- `location.field` can be all `null`; `remarks` can be `null`.
- A team's own matches: filter `matches[]` on `home.id` or `away.id` equal to the team `id`.

## Match details

`GET /matches/{id}` adds to the match object:

- `weather`: the forecast for the match's time and place, also for youth matches:
  `condition_code` (`PartlyCloudy`, …), `temperature`, `temperature_apparent` (°C),
  `precipitation_type` (`clear`, `rain`, …), `precipitation_chance` (%), `precipitation_amount`,
  `humidity`, `rating` (`fantastic`, …), `grade` (1–10), `description` (a Dutch sentence, such as
  *"Brrr… Het wordt koud vandaag."*) and `icon` (`vector`, `raster`, `name`).
- `approved_by_home_team`, `approved_by_away_team`: whether each team approved the result
  (`false` before the match).
- `actions[]`: the digital match form, where one was used (mostly top-level senior matches): `action`
  (`match`, `goal`, `card`, …), `action_type` (`start`, `pause`, `goal-pc`, `card-yellow`, …), `side`,
  `seconds_since_start`, `team_id` and **`person_name`**: names of players, so personal data (of
  children too, in youth matches). The integration does not use them.
- `videos[]`.

## Other pools of a team (`neighbors`)

Each entry has `poule_id`, `season_id`, `season_name`, `period_name`, `name` and `poule_name`. Entries
with the same `season_id` as the team page are the team's other pools this season: cup rounds (for
example *Gold Cup – KO ronde 2* for a senior team) or an earlier period (*Voorcompetitie* for youth
teams). Older entries are past seasons. Fetching a neighbor with the same team id gives that pool's
team page. A finished youngest-youth *Voorcompetitie* pool came back with no matches at all.

## Standing object

`rank`, `played`, `points`, `wins`, `draws`, `losses`, `goals_for`, `goals_against`, `penalties`,
`change` / `rank_change`, and `team` (same shape as in a match).

Pools of the youngest age groups (*Jongste jeugd*) have no standings: `standings` is an empty list.

## Being a good citizen

What the integration does per team:

- the team page every 30 minutes; every 5 minutes from half an hour before one of the team's own
  matches until its result is in (at most 3 hours after the start); every 2 hours when the team has
  no upcoming matches;
- the club's team list (for `recent_poule_id`) every 12 hours, and at once when the pool answers 404;
- the team's other pools of this season every 6 hours, or every 5 minutes around a match in them;
- the details of the next match (for its weather forecast) every 3 hours, from 48 hours before it;
- at Home Assistant start-up only the team page; the rest follows a minute later.

One device registration per config entry, reused until a 401.

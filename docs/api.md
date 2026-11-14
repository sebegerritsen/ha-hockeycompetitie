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

A logged-in user adds `Authorization: Bearer <id_token>` from the KNHB login; not needed for public data.

## Endpoints used

| Endpoint | What it returns |
|---|---|
| `GET /clubs` | All clubs: `federation_reference_id` (e.g. `HH11AB1`), `name`, `friendly_name`, `city`, `logo`, `type` (`regular` or `business`). |
| `GET /clubs/{federation_reference_id}` | Club details plus `teams`: `id`, `name`, `short_name` (`JO14-2`, `MO10-Geel`, …), `hockey_type` (`VE` field, `ZA` indoor), `category_group_name` (`Jongste jeugd`, `Junioren`, `Senioren`), `recent_poule_id`. |
| `GET /poules/{poule_id}/teams/{team_id}` | The team page: `data.poules[]`, each with `competition`, `standings[]` and `matches[]` (all matches in that pool, not only the team's own). Use the team's `recent_poule_id`; it changes when a new competition period starts, so refresh it from `/clubs/{id}` now and then. |
| `GET /matches/{id}` | One match in detail, adding `weather` (forecast for the match), `actions`, `videos`, approvals. |
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

- `status` values seen: `scheduled`, `announced`, `final`. The match centre code also knows live and
  result states; cancellations are expected to show up in `status` and `cancellation_minute`. To confirm.
- `remarks` can be `null`.
- A team's own matches: filter `matches[]` on `home.id` or `away.id` equal to the team `id`.

## Standing object

`rank`, `played`, `points`, `wins`, `draws`, `losses`, `goals_for`, `goals_against`, `penalties`,
`change` / `rank_change`, and `team` (same shape as in a match).

## Being a good citizen

The integration should poll no more than needed: team pages every 30 minutes, more often only around
a team's own matches, and the club's team list (for `recent_poule_id`) about twice a day. One device
registration per Home Assistant config entry, reused until a 401.

# KNHB Hockey: notes for working on this repo

Public open-source project (GitHub: sebegerritsen/ha-knhb-hockey), meant for HACS. Everything in
this repo is public: **no personal data** — no names of family members, no real rosters, no tokens,
no details of the owner's home setup. Use made-up teams/clubs or anonymised data in tests and examples.

## What it is

A Home Assistant custom integration (`custom_components/knhb_hockey`, domain `knhb_hockey`) for
Dutch hockey match data from the KNHB, the source behind hockey.nl's match centre. How the API works
(device registration, request signing, endpoints, data shapes): docs/api.md. `tools/probe.py` calls it
from the command line.

Decided (Nov 2026):
- Generic KNHB data, not LISA: works for every club without a login. LISA (club software, per-member
  login: trainings, attendance, duties) may come later as an optional extra.
- One config entry per team. Config flow: search club → pick team (label `JO14-2 · Veld · Junioren`).
  Store club id, team id, names, hockey type, and the device UUID + token (re-register on 401).
- Per team: a calendar entity (all own matches; ~90 min events; title home – away, score when
  final; location = venue + address; description = pitch, competition, remarks), sensors
  next match (timestamp + attributes), last result, standing.
- DataUpdateCoordinator: team page every 30 min (shorter around own matches), club team list
  ~twice a day to refresh `recent_poule_id`.
- Translations en + nl. Modern HA patterns: `entry.runtime_data`, `has_entity_name` +
  `translation_key`, coordinator with `config_entry=`, diagnostics with token/uuid redacted.
- HACS: hacs.json, manifest with version, GitHub Actions for hassfest + HACS validation.

## Testing locally

Copy `custom_components/knhb_hockey` into your Home Assistant `custom_components/` folder and restart
Home Assistant (a new custom integration needs a restart). Personal setup notes (paths, hosts) belong
in `CLAUDE.local.md`, which is git-ignored.

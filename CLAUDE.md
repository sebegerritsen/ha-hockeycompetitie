# Hockeycompetitie: notes for working on this repo

Public open-source project (GitHub: sebegerritsen/ha-hockeycompetitie), meant for HACS. Everything in
this repo is public: **no personal data** — no names of family members, no real rosters, no tokens,
no details of the owner's home setup. Use made-up teams/clubs or anonymised data in tests and examples.

## What it is

A Home Assistant custom integration (`custom_components/hockeycompetitie`, domain `hockeycompetitie`) for
Dutch hockey match data from the KNHB, the source behind hockey.nl's match centre. How the API works
(device registration, request signing, endpoints, data shapes): docs/api.md. `tools/probe.py` calls it
from the command line.

Decided (Nov 2026):
- Named **Hockeycompetitie** (domain `hockeycompetitie`; "KNHB Hockey"/`knhb_hockey` until 15 Nov 2026) so
  it doesn't look like an official KNHB product: no "KNHB" in the name, domain or icon. The KNHB is
  named only as the data source, with "not affiliated". Same rule as the sibling integrations
  Competitie Voetbal and Tenniscompetitie.
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

## Releasing

HACS installs from GitHub releases. For a new version: bump `version` in
`custom_components/hockeycompetitie/manifest.json`, commit, wait for CI (Tests + Validate) to pass, then
`gh release create vX.Y.Z --title vX.Y.Z --notes "…"` (the tag must match the manifest version; a full release,
not just a tag). A README-only change needs no release. Submitted to the HACS default list on 15 Nov 2026
(hacs/default PR #14206); never ask HACS maintainers for a review, it gets the PR closed.

## Testing locally

Copy `custom_components/hockeycompetitie` into your Home Assistant `custom_components/` folder and restart
Home Assistant (a new custom integration needs a restart). Personal setup notes (paths, hosts) belong
in `CLAUDE.local.md`, which is git-ignored.

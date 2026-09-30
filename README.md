# Local League — MLB The Show tournament manager

A local, mobile-friendly tournament app for eight two-player teams and two gaming setups. Python/Flask, Waitress, SQLite, and locally served HTML/CSS/JavaScript. No account, cloud service, frontend build process, or runtime internet connection is required.

## Run on this computer

The project environment is already installed in this workspace:

```bash
.venv/bin/python run.py
```

Open **http://localhost:8080**. On another device on the same network, use **http://YOUR_COMPUTER_IP:8080**. Stop the server with Ctrl+C.

For a fresh installation (Python 3.10 or newer):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

The first page guides you through team setup. You can draw one partner from each of two eight-player pools, rename teams, randomize or manually assign the groups, and review the setup. An unfinished setup draft stays in the browser that created it. Once created, the shared tournament lives on the server.

## Game-day workflow

1. Set the date, start time, timezone, estimated game length, breaks, field names, and optional pitcher suggestions.
2. Enter eight teams with two distinct players each. Four teams go in each group.
3. Group A stays on field 1; group B stays on field 2. The group match order minimizes consecutive games. Each team gets one or two home games.
4. Open a game to save its pitchers, mark it started, or enter a final score. A result can be recorded without pressing Start first. Review the score, then confirm it. Tied final scores are rejected.
5. After the groups finish, resolve any remaining ties on Standings by recording the order drawn in person.
6. The fixed bracket advances automatically: A1–B4, A2–B3, A3–B2, A4–B1. QF1/QF2 feed SF1; QF3/QF4 feed SF2. Semifinals are best of three, final best of five.
7. Check Playoffs for any tied home-advantage draw. Home alternates in each series. Unneeded games are marked accordingly.
8. Use Teams & pitchers for each team's pitcher history. Download a JSON backup from Tournament setup.

All connected users can edit, as requested. The server rejects stale edits instead of silently overwriting another phone's submission. Score corrections recalculate standings and future opponents. If recorded downstream games become invalid, the app lists them and asks before clearing them. Reopening a game removes its completion and can require clearing subsequent games; use a score correction for ordinary typos.

Times are estimates. A ready game may start early by agreement. Pausing a field prevents new games from starting until you resume it manually. An indefinite pause makes dependent future times TBD. Both groups finish before quarterfinals; all quarterfinals finish before semifinals; the final waits for both semifinal winners.

## Ranking and home advantage

- Group order: wins; head-to-head when exactly two teams are tied on wins; overall group run differential; overall group runs scored; manual draw.
- For three or more teams tied on wins, skip head-to-head. Do not restart head-to-head on smaller subsets.
- Quarterfinal home: better group placement.
- Series opening home: better group placement, group wins, group run differential, group runs scored, then manual draw. Home alternates H/A/H or H/A/H/A/H.
- No third-place game. Total played games: 23–27.

## Persistent data and backups

Default data directory: **data/** in the project. It contains tournament.sqlite3 (plus SQLite journal files while running) and backups/ created before reset/restore. SQLite stores the small tournament as a versioned JSON snapshot inside a transaction, with a revision counter, submission identifiers, and before/after change history. This keeps the schema simple while making shared writes atomic.

Use the in-app **Download JSON backup** for a consistent portable snapshot. It includes settings, players, groups, games, pitchers, pauses, and draw decisions. It does not include the separate historical change log. Restore validates the entire tournament before changing live data, and retains local pre-restore state and history.

For a full archive including history, stop the server/service and copy the entire data directory. Keep the Pi's clock correct before game day; actual game timestamps drive estimates.

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| TOURNAMENT_DATA_DIR | project/data | Persistent database and backups |
| TOURNAMENT_HOST | 0.0.0.0 | Listen on local network interfaces |
| TOURNAMENT_PORT | 8080 | Web port |
| TOURNAMENT_PUBLIC_URL | Automatically detected LAN address | Optional fixed QR-code destination |

The service template uses **~/.local/share/local-league/** for data instead, keeping data outside the source directory.

## Raspberry Pi installation and existing Wi-Fi

See [docs/RASPBERRY_PI.md](docs/RASPBERRY_PI.md) for installation, optional startup at boot, access over your existing Wi-Fi, the phone URL, and a game-day checklist. Connect the host and phones to the same local network; no dedicated hotspot is needed. The app is intended for a trusted local network; there is no authentication because everyone should be able to enter results.

## Development and tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check static/app.js
```

The suite covers group rules, manual ties, home assignment, 23/27-game tournaments, delays and breaks, corrections, concurrent phone edits, duplicate submissions, restart persistence, backup validation, and real-browser score entry.

Browser tests use installed Chrome or Chromium and an isolated test server/database. Set BROWSER_EXECUTABLE to its path if needed. They skip if no browser is available. Tests save desktop/mobile screenshots to test-results/; none of the test teams or scores are put in the live database.

Project layout:

- tournament/domain.py — rules, validation, advancement, estimates.
- tournament/storage.py — SQLite transactions, backups, revisions, history.
- tournament/app.py — same-origin JSON API and page serving.
- templates/ and static/ — mobile interface, local assets, live polling.
- tests/ — rules, API, concurrency, persistence, browser tests.
- deploy/ — systemd service template.
- PLAN.md — original design and implementation notes.

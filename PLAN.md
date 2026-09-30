# Local MLB The Show tournament app

Status: implemented. See README.md for running the app and docs/RASPBERRY_PI.md for deployment. Automated rules, API, persistence, concurrency, and desktop/mobile Chrome checks are included; physical Pi Wi-Fi connectivity and optional boot behavior still require an on-device rehearsal.

## Confirmed requirements

- One local tournament, eight teams, two fixed players per team. All teams use the same MLB roster.
- Two groups of four. Each group plays on its own gaming setup, with both setups running in parallel.
- Single round robin: six games per group, twelve group games total.
- Everyone advances. Quarterfinals: QF1 A1–B4, QF2 A2–B3, QF3 A3–B2, QF4 A4–B1.
- Fixed semifinals: winner QF1–winner QF2, winner QF3–winner QF4.
- Quarterfinals are single games; semifinals best of three; final best of five. Total: 23–27 played games.
- No draws. Record each game's final runs and each team's starting pitcher. Pitcher tracking is informational only.
- Higher group placement earns home in quarterfinals. Alternate home/away in semifinal and final series.
- Anyone with access can enter scores and pitchers; no account or organizer password required.
- Game order is authoritative; times are estimates. Games typically last 20–30 minutes.
- Persist tournament state on the Raspberry Pi and operate without an internet connection.

## Proposed defaults

These fill minor gaps and can be changed during setup without blocking implementation.

- English interface; editable tournament name, date, start time, and local timezone (initially Europe/Berlin).
- Estimate 25 minutes per game, five minutes between games, and at least ten minutes of rest for a team scheduled consecutively. When necessary, the extra rest creates idle time on its setup.
- A ten-minute minimum team rest also applies between phases; it is not added twice on top of an already sufficient break.
- Groups can be assigned manually or randomized, with four teams in each.
- No third-place game.
- Series opening home team is determined by better group placement, then group wins, group run differential, group runs scored, then a recorded manual draw. These comparisons use group results only.
- A team's series home pattern is H/A/H or H/A/H/A/H when it earns opening home advantage.
- Group home assignments are balanced: each team has either one or two home games.
- Pitcher fields can be saved before play or added later; missing pitchers do not block results or advancement.
- Unresolved manual decisions are explicitly shown as pending; the app never invents a draw result.

## Screens and user flow

### Setup

Enter eight team names and sixteen distinct players, then assign two players per team and four teams per group. Configure timing and setup names. Preview the groups and opening schedule before starting.

Optional draw helper: enter eight stronger players and eight other players, shuffle the second list, and pair one from each list. Preview, rename teams, and confirm. Persist the accepted draw; page refreshes never redraw. This convenience feature follows the core tournament features.

### Live dashboard and schedule

Show both setups with their current game and next game, followed by the full game order. Every match shows phase, setup, home/away, players, estimated time, score/status, and a clear result-entry action. Provide team and setup filters. Mobile cards are the primary layout, with a wider two-column view for a laptop/display.

Label times as estimated. Show an obvious connection status and last successful refresh. Poll for updates approximately every five seconds without replacing unsaved form fields. Do not claim that unsaved or failed submissions were saved.

### Game entry

Allow users to mark a ready game started, record its pitchers independently of its score, and submit a final score. Allow recording a completed game even when nobody pressed Start. Scores must be nonnegative integers and cannot be equal when finalized. Saving final runs and updating the winner happen together.

Show the teams, home/away roles, and entered result before final submission. Allow correction of saved information. Use version checks so a stale phone cannot silently overwrite a newer submission; present the latest record and ask the user to reconcile it. Retried identical submissions must not advance a series twice.

### Standings and bracket

Group tables show played, wins, losses, runs for, runs against, run differential, and position. Bracket cards show participants or source placeholders, individual results, series score, next game, and winner.

Sort group standings by wins. For exactly two teams tied on wins, use their completed head-to-head result, then overall group run differential, then overall group runs scored. For three or more teams tied on wins, skip head-to-head and use overall group run differential and then overall group runs scored. Any remaining tie is resolved by manually recording the order drawn in person. Do not restart the head-to-head criterion on smaller subsets of a multi-team tie. During incomplete group play, rankings are provisional.

Only finalize knockout seeds after every group result and relevant manual tie decision is settled. Invalidate a saved draw decision if a correction changes its tied cohort or the standings evidence on which it depends.

### Teams and pitcher history

Each team has a page listing both players, upcoming games, results, and starting pitcher for every game in chronological order. Offer a shared editable pitcher-name list with free-text entry. Do not enforce a rotation, eligibility, or warnings.

### Data controls

Provide JSON export and validated restore of a versioned tournament snapshot. Create a local backup before replacing existing state. Require explicit confirmation for replacement, reset, and any correction that invalidates recorded downstream games. Show a simple recent-change history; without logins this records what changed and when, not a verified person's identity.

## Scheduling and advancement

### Group stage

Use this order independently for each group, where numbers identify teams rather than seeds:

1. 1 vs 2
2. 3 vs 4
3. 1 vs 3
4. 2 vs 4
5. 1 vs 4
6. 2 vs 3

All six pairs occur once. Three adjacent transitions involve disjoint teams; two transitions require one team to play consecutively. Two such transitions are the minimum possible for six games on one setup. Assign team numbers randomly when generating the schedule and retain the assignment. Apply the configured rest time at consecutive appearances.

### Knockout stage

- Start quarterfinals after both groups finish and seeds are resolved.
- Setup 1 hosts QF1 then QF2; setup 2 hosts QF3 then QF4.
- After all quarterfinals finish, setup 1 hosts SF1 and setup 2 hosts SF2. Each semifinal plays its series consecutively, with breaks.
- Start the final on setup 1 after both semifinal winners are known and required rest has elapsed.
- A series ends immediately when a team reaches two semifinal wins or three final wins. Unneeded games are retained as “not needed” for clarity and excluded from future time estimates.
- Show SF game 3 and final games 4–5 as “if needed.” Future phase estimates initially reserve the maximum possible series length and become earlier when games become unnecessary.
- Never allow a team or setup to have two ongoing games. Readiness requires known participants, completed dependencies, and an available setup.

### Time estimates

Calculate each planned start from the latest of setup availability, participant availability plus minimum rest, and phase prerequisites. Include setup turnaround without double-counting overlapping team rest. Base the initial timetable on the configured start; after play begins, use actual starts/completions and estimates for remaining games.

If an ongoing game exceeds its estimated duration, mark it running long and keep upcoming estimates at or after the present plus applicable breaks. Completed and ongoing assignments remain fixed. Recalculate future estimates after results, pauses, and timing adjustments; do not automatically mark games started when their estimated time arrives. Permit explicit pauses and estimated resume times per setup.

### Corrections after advancement

Recompute standings, series totals, and dependent unstarted match assignments after a correction. If a changed seed or winner would invalidate an ongoing/completed downstream game, show the affected games and require an explicit reopen/reset of those dependent games before applying that correction. Preserve prior records in history. Pitcher edits and score corrections that do not change participants can proceed without clearing unrelated games.

## Technical design

- Python with Flask, served by Waitress, in a virtual environment.
- Server-rendered HTML, local CSS, and small JavaScript modules for updates and score forms. No frontend build tool, CDN, external fonts, or runtime cloud dependency.
- SQLite through Python's standard library. One database file, no separate database service. Use transactions and short serialized writes; SQLite alone does not replace stale-edit checks.
- Keep database, backups, and logs outside source files, with configurable paths and schema versioning.
- Persist settings, players, teams, group membership, games, series, seed/home draw decisions, revisions, and change history. Derive standings from final group results and series wins from final series games.
- Store actual event timestamps consistently and render in the tournament timezone.
- Validate all writes on the server, use parameterized queries, escape user-provided names, and require same-origin write requests.
- Expose a small JSON API to the local browser interface. Keep tournament rules and schedule calculations separate from HTTP routes so they can be tested directly.
- Bind the production service to the local network on a documented port, e.g. 8080. Use systemd to start it after boot and restart after process failure. It must work even without an Ethernet uplink.

SQLite is proposed instead of a directly rewritten JSON file because multiple phones can submit changes concurrently. JSON remains the portable export/restore format. SQLite transactions and explicit application revision checks handle different parts of reliable shared editing.

## Raspberry Pi deployment

Updated after implementation: use the existing Wi-Fi network shared by the host and phones. A dedicated Pi hotspot and Ethernet internet sharing are no longer requirements. The host can be a Raspberry Pi or Ubuntu PC.

Run the app listening on the local network, and open `http://HOST_WIFI_IP:8080` on phones. Document installation, the host’s Wi-Fi address, optional automatic startup, persistent storage, backup/restore, and local-network troubleshooting. Generate the QR code from the network URL so it points to the host rather than a phone’s localhost. The local app remains usable without upstream internet as long as the Wi-Fi network is available.

References consulted during planning:

- Raspberry Pi network configuration: https://www.raspberrypi.com/documentation/computers/configuration.html
- Python SQLite documentation: https://docs.python.org/3/library/sqlite3.html
- Flask deployment with Waitress: https://flask.palletsprojects.com/en/stable/deploying/waitress/

## Implementation sequence and acceptance checks

1. **Tournament rules and storage:** schema, setup, group matches, ranking, bracket, home assignments, series advancement. Verify twelve unique group games, three appearances per team, every ranking/tie path, fixed bracket mapping, and early series finishes.
2. **Schedule and mobile screens:** dashboard, filters, game entry, standings, bracket, team histories. Verify setup confinement during groups, rest calculation, phase dependencies, delayed games, and “if needed” estimates.
3. **Shared editing and recovery:** revisions, correction handling, change history, export/restore. Verify conflicting phone edits, duplicate submissions, invalid scores, upstream corrections, restart persistence, and a backup/restore round trip.
4. **Convenience and deployment:** player draw helper, local QR code, service files, and Pi/existing-Wi-Fi instructions. Verify the draw uses every player exactly once and survives reload.
5. **Complete rehearsal:** simulate both a shortest tournament (23 games) and longest tournament (27 games), including a manual group tie, score correction, pitcher edits, and process restart. On the actual Pi, test simultaneous phones, automatic startup, and access from phones on the existing Wi-Fi.

Implementation can start from this plan without additional rules clarification. Proposed defaults remain visible and adjustable; physical network and on-device checks require access to the Raspberry Pi.

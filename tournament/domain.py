"""Tournament rules. All mutations operate on a private transaction snapshot."""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RuleError(ValueError):
    def __init__(self, message, affected=None):
        super().__init__(message)
        self.affected = affected or []


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise RuleError("Use a valid date and time with a timezone.") from None


def text(value, label, maximum=100, blank=False):
    if not isinstance(value, str) or len(value.strip()) > maximum or (not blank and not value.strip()):
        raise RuleError(f"{label} must contain {'0' if blank else '1'}–{maximum} characters.")
    return value.strip()


def integer(value, label, low=0, high=999):
    if type(value) is not int or not low <= value <= high:
        raise RuleError(f"{label} must be a whole number between {low} and {high}.")
    return value


def settings_from(data):
    if not isinstance(data, dict):
        raise RuleError("Tournament settings are missing.")
    zone = text(data.get("timezone", "Europe/Berlin"), "Timezone")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise RuleError("Choose a valid timezone, such as Europe/Berlin.") from None
    start = timestamp(data.get("start"))
    names = data.get("setup_names", ["Field 1", "Field 2"])
    if not isinstance(names, list) or len(names) != 2:
        raise RuleError("Give both setups a name.")
    pitchers = data.get("pitchers", [])
    if not isinstance(pitchers, list) or len(pitchers) > 100:
        raise RuleError("Enter up to 100 pitcher names.")
    return {
        "name": text(data.get("name"), "Tournament name"), "timezone": zone,
        "start": start.isoformat(),
        "game_minutes": integer(data.get("game_minutes", 25), "Game estimate", 1, 180),
        "break_minutes": integer(data.get("break_minutes", 5), "Setup break", 0, 120),
        "rest_minutes": integer(data.get("rest_minutes", 10), "Team rest", 0, 120),
        "setup_names": [text(n, "Setup name", 50) for n in names],
        "pitchers": list(dict.fromkeys(text(n, "Pitcher", 100) for n in pitchers)),
    }


def blank_game(id_, phase, setup, sequence, home=None, away=None, series=None, number=1):
    return dict(id=id_, phase=phase, setup=setup, sequence=sequence, home=home, away=away,
                series=series or id_, number=number, status="scheduled", home_score=None,
                away_score=None, home_pitcher="", away_pitcher="", started_at=None,
                completed_at=None)


def new_tournament(data, shuffle=True):
    if not isinstance(data, dict):
        raise RuleError("Provide tournament setup details.")
    settings = settings_from(data.get("settings"))
    raw = data.get("teams")
    if not isinstance(raw, list) or len(raw) != 8:
        raise RuleError("Exactly eight teams are required.")
    teams = []
    for i, team in enumerate(raw):
        if not isinstance(team, dict) or not isinstance(team.get("players"), list) or len(team["players"]) != 2:
            raise RuleError("Every team needs two players.")
        if team.get("group") not in ("A", "B"):
            raise RuleError("Assign every team to group A or B.")
        teams.append(dict(id=f"T{i+1}", name=text(team.get("name"), "Team name"),
                          players=[text(p, "Player name") for p in team["players"]], group=team["group"]))
    if len({t["name"].casefold() for t in teams}) != 8:
        raise RuleError("Team names must be distinct.")
    if len({p.casefold() for t in teams for p in t["players"]}) != 16:
        raise RuleError("Enter sixteen distinct player names (use nicknames if needed).")
    if Counter(t["group"] for t in teams) != {"A": 4, "B": 4}:
        raise RuleError("Each group needs four teams.")
    groups = {g: [t["id"] for t in teams if t["group"] == g] for g in "AB"}
    if shuffle:
        for members in groups.values():
            secrets.SystemRandom().shuffle(members)
    games = []
    # Orientations give every team one or two home games.
    for setup, group in enumerate("AB", 1):
        members = groups[group]
        for n, (h, a) in enumerate([(0, 1), (2, 3), (0, 2), (1, 3), (3, 0), (1, 2)], 1):
            games.append(blank_game(f"{group}{n}", "group", setup, n, members[h], members[a]))
    for n in range(1, 5):
        games.append(blank_game(f"QF{n}", "quarterfinal", 1 if n <= 2 else 2, 7 + (n-1) % 2))
    for series, setup in [("SF1", 1), ("SF2", 2)]:
        for n in range(1, 4):
            games.append(blank_game(f"{series}-{n}", "semifinal", setup, 8+n, series=series, number=n))
    for n in range(1, 6):
        games.append(blank_game(f"F-{n}", "final", 1, 11+n, series="F", number=n))
    return dict(schema_version=1, settings=settings, teams=teams, groups=groups, games=games,
                ties={}, home_draws={}, pauses={"1": None, "2": None}, created_at=now_iso())


def evidence(state, group=None):
    values = [(g["id"], g["home_score"], g["away_score"], g["status"])
              for g in state["games"] if g["phase"] == "group" and (not group or g["id"].startswith(group))]
    return sha256(json.dumps(values).encode()).hexdigest()


def standings(state):
    result = {}
    for group in "AB":
        rows = {id_: dict(team=id_, played=0, wins=0, losses=0, rf=0, ra=0, rd=0) for id_ in state["groups"][group]}
        games = [g for g in state["games"] if g["phase"] == "group" and g["home"] in rows]
        for game in games:
            if game["status"] != "completed":
                continue
            for own, other in [("home", "away"), ("away", "home")]:
                row = rows[game[own]]
                row["played"] += 1
                row["rf"] += game[f"{own}_score"]
                row["ra"] += game[f"{other}_score"]
                row["wins"] += int(game[f"{own}_score"] > game[f"{other}_score"])
                row["losses"] = row["played"] - row["wins"]
                row["rd"] = row["rf"] - row["ra"]
        ordered, unresolved = [], []
        decision = state["ties"].get(group, {})
        manual = decision.get("order", []) if decision.get("signature") == evidence(state, group) else []
        for wins in sorted({r["wins"] for r in rows.values()}, reverse=True):
            cohort = [r for r in rows.values() if r["wins"] == wins]
            h2h = None
            if len(cohort) == 2:
                ids = {r["team"] for r in cohort}
                h2h = next((winner(g) for g in games if {g["home"], g["away"]} == ids and g["status"] == "completed"), None)
            def rank(row):
                return (int(row["team"] == h2h), row["rd"], row["rf"])
            cohort.sort(key=rank, reverse=True)
            for key in sorted({rank(r) for r in cohort}, reverse=True):
                tied = [r for r in cohort if rank(r) == key]
                if len(tied) > 1:
                    ids = [r["team"] for r in tied]
                    if manual and all(id_ in manual for id_ in ids):
                        tied.sort(key=lambda r: manual.index(r["team"]))
                    else:
                        unresolved.append(ids)
                ordered.extend(tied)
        for pos, row in enumerate(ordered, 1):
            row["position"] = pos
        complete = all(g["status"] == "completed" for g in games)
        result[group] = dict(rows=ordered, complete=complete, unresolved=unresolved if complete else [],
                             resolved=complete and not unresolved)
    return result


def winner(game):
    if game["status"] != "completed":
        return None
    return game["home"] if game["home_score"] > game["away_score"] else game["away"]


def series_winner(state, series):
    games = [g for g in state["games"] if g["series"] == series]
    needed = 3 if series == "F" else 2 if series.startswith("SF") else 1
    wins = Counter(winner(g) for g in games if winner(g))
    return next((t for t, n in wins.items() if n >= needed), None)


def opening_home(state, series, left, right, tables):
    if not left or not right:
        return None
    rows = {r["team"]: r for table in tables.values() for r in table["rows"]}
    def rank(team):
        r = rows[team]
        return (-r["position"], r["wins"], r["rd"], r["rf"])
    if rank(left) != rank(right):
        return max([left, right], key=rank)
    decision = state["home_draws"].get(series, {})
    signature = evidence(state) + ":" + ":".join(sorted([left, right]))
    if decision.get("signature") == signature and decision.get("team") in (left, right):
        return decision["team"]
    return None


def clear_game(game):
    game.update(status="scheduled", home_score=None, away_score=None, home_pitcher="", away_pitcher="",
                started_at=None, completed_at=None)


def reconcile(state, allow_reset=False):
    """Propagate seeds/winners; refuse to silently invalidate downstream play."""
    tables = standings(state)
    seeded = all(t["resolved"] for t in tables.values())
    seeds = {g: [r["team"] for r in table["rows"]] for g, table in tables.items()}
    by_id = {g["id"]: g for g in state["games"]}
    affected = []
    def assign(game, home, away, unused=False):
        changed = (game["home"], game["away"]) != (home, away)
        invalid = (changed or unused) and game["status"] in ("ongoing", "completed")
        if invalid:
            affected.append(game["id"])
        if changed or invalid:
            clear_game(game)
        game.update(home=home, away=away)
        if unused:
            game["status"] = "not_needed"
        elif game["status"] == "not_needed":
            game["status"] = "scheduled"
    for n in range(1, 5):
        a, b = (seeds["A"][n-1], seeds["B"][4-n]) if seeded else (None, None)
        assign(by_id[f"QF{n}"], a if n <= 2 else b, b if n <= 2 else a)
    pending = []
    for series, sources, length in [("SF1", ["QF1", "QF2"], 3), ("SF2", ["QF3", "QF4"], 3), ("F", ["SF1", "SF2"], 5)]:
        left, right = [series_winner(state, src) for src in sources]
        home = opening_home(state, series, left, right, tables)
        if left and right and not home:
            pending.append(dict(series=series, teams=[left, right]))
        away = (right if home == left else left) if home else None
        wins = Counter()
        for n in range(1, length+1):
            game = by_id[f"{series}-{n}"]
            unused = max(wins.values(), default=0) >= length//2+1
            assign(game, home if n % 2 else away, away if n % 2 else home, unused)
            if winner(game):
                wins[winner(game)] += 1
    if affected and not allow_reset:
        raise RuleError("This change invalidates recorded downstream games. Confirm to reset the listed games; their old records remain in history.", affected)
    return pending, affected


def ready(state, game, check_busy=True):
    if game["status"] != "scheduled" or not game["home"] or not game["away"]:
        return False
    if state["pauses"].get(str(game["setup"])):
        return False
    phase = game["phase"]
    required = {"group": [], "quarterfinal": ["group"], "semifinal": ["group", "quarterfinal"], "final": ["group", "quarterfinal", "semifinal"]}[phase]
    for prior in state["games"]:
        finished = prior["status"] in ("completed", "not_needed")
        if prior["phase"] in required and not finished:
            return False
        if prior["setup"] == game["setup"] and prior["sequence"] < game["sequence"] and not finished:
            return False
        if check_busy and prior["status"] == "ongoing" and (prior["setup"] == game["setup"] or {prior["home"], prior["away"]} & {game["home"], game["away"]}):
            return False
    return True


def schedule(state, now=None):
    now = now or datetime.now(timezone.utc)
    settings = state["settings"]
    start = timestamp(settings["start"])
    duration = timedelta(minutes=settings["game_minutes"])
    gap = timedelta(minutes=settings["break_minutes"])
    rest = timedelta(minutes=settings["rest_minutes"])
    fields, teams, result = {1: start, 2: start}, {}, {}
    recorded = [timestamp(g["started_at"] or g["completed_at"]) for g in state["games"] if g["status"] in ("ongoing", "completed")]
    active = bool(recorded)
    if recorded:
        start = min(start, min(recorded))
        fields = {1: start, 2: start}
    phase_floor = start
    unknown_by_phase = set()
    for phase in ["group", "quarterfinal", "semifinal", "final"]:
        phase_ends = []
        for game in sorted([g for g in state["games"] if g["phase"] == phase], key=lambda g: (g["sequence"], g["setup"])):
            if game["status"] == "not_needed":
                result[game["id"]] = dict(estimated_start=None, estimated_end=None, running_long=False, paused=False)
                continue
            field = game["setup"]
            pause = state["pauses"].get(str(field))
            actual = game["status"] in ("completed", "ongoing")
            uncertain = not actual and (field in unknown_by_phase or (pause is not None and pause["until"] is None))
            if not actual and any(f in unknown_by_phase for f in (1, 2)) and phase != "group":
                uncertain = True
            candidates = [phase_floor, fields[field]]
            for team in (game["home"], game["away"]):
                if team in teams:
                    candidates.append(teams[team]+rest)
            if active or now > start:
                candidates.append(now)
            if pause and pause["until"]:
                candidates.append(max(now, timestamp(pause["until"])))
            estimate = max(candidates)
            if game["status"] == "completed":
                end = timestamp(game["completed_at"])
                begin = timestamp(game["started_at"]) if game["started_at"] else end-duration
            elif game["status"] == "ongoing":
                begin = timestamp(game["started_at"])
                end = max(begin+duration, now)
            else:
                begin, end = estimate, estimate+duration
            if uncertain:
                unknown_by_phase.add(field)
            fields[field] = end+gap
            for team in (game["home"], game["away"]):
                if team:
                    teams[team] = end
            result[game["id"]] = dict(estimated_start=None if uncertain else begin.isoformat(),
                                      estimated_end=None if uncertain else end.isoformat(),
                                      running_long=game["status"] == "ongoing" and now > begin+duration,
                                      paused=bool(pause) and not actual)
            phase_ends.append(end)
        if phase_ends:
            # Unknown knockout participants may come from the last game of this phase.
            phase_floor = max(phase_ends) + max(gap, rest)
    return result


def view(state, revision, now=None):
    if state is None:
        return dict(revision=revision, tournament=None)
    state = deepcopy(state)
    pending, _ = reconcile(state)
    estimates = schedule(state, now)
    for game in state["games"]:
        game.update(estimates[game["id"]], ready=ready(state, game), winner=winner(game),
                    if_needed=(game["phase"] == "semifinal" and game["number"] == 3) or (game["phase"] == "final" and game["number"] >= 4))
    state.update(standings=standings(state), pending_home=pending, champion=series_winner(state, "F"))
    return dict(revision=revision, tournament=state)


def mutate(state, action):
    if not isinstance(action, dict):
        raise RuleError("Invalid change request.")
    kind = action.get("type")
    if kind == "settings":
        state["settings"] = settings_from(action.get("settings"))
    elif kind == "tie":
        group = action.get("group")
        order = action.get("order")
        if group not in ("A", "B") or not isinstance(order, list) or not all(isinstance(t, str) for t in order) or sorted(order) != sorted(state["groups"][group]):
            raise RuleError("Record the drawn order using each group team exactly once.")
        if not standings(state)[group]["complete"]:
            raise RuleError("Finish the group before recording a draw.")
        state["ties"][group] = dict(order=order, signature=evidence(state, group))
    elif kind == "home_draw":
        pending, _ = reconcile(state)
        match = next((p for p in pending if p["series"] == action.get("series")), None)
        if not match or action.get("team") not in match["teams"]:
            raise RuleError("Choose a team from the pending home draw.")
        state["home_draws"][match["series"]] = dict(team=action["team"], signature=evidence(state)+":"+":".join(sorted(match["teams"])))
    elif kind == "pause":
        field = str(action.get("setup"))
        if field not in ("1", "2"):
            raise RuleError("Choose a valid setup.")
        if action.get("paused") is True:
            until = action.get("until")
            if until:
                until = timestamp(until).isoformat()
            state["pauses"][field] = dict(until=until or None)
        else:
            state["pauses"][field] = None
    elif kind in ("start", "score", "pitchers", "reopen"):
        game = next((g for g in state["games"] if g["id"] == action.get("game")), None)
        if not game:
            raise RuleError("Game not found.")
        if kind == "reopen":
            clear_game(game)
            phases = ["group", "quarterfinal", "semifinal", "final"]
            affected = [g["id"] for g in state["games"]
                        if g["status"] in ("ongoing", "completed") and
                        ((g["setup"] == game["setup"] and g["sequence"] > game["sequence"]) or
                         phases.index(g["phase"]) > phases.index(game["phase"]))]
            if affected and action.get("confirm_reset") is not True:
                raise RuleError("Reopening this game also resets later recorded games on this field and in later stages.", affected)
            for g in state["games"]:
                if g["id"] in affected:
                    clear_game(g)
        else:
            if not game["home"] or not game["away"] or game["status"] == "not_needed":
                raise RuleError("This game's participants are not ready.")
            if kind == "start":
                if not ready(state, game):
                    raise RuleError("Finish earlier games and resume the setup before starting this game.")
                game.update(status="ongoing", started_at=now_iso())
            if kind == "score":
                h = integer(action.get("home_score"), "Home runs")
                a = integer(action.get("away_score"), "Away runs")
                if h == a:
                    raise RuleError("A final score cannot be tied. Finish extra innings first.")
                if game["status"] == "scheduled" and not ready(state, game):
                    raise RuleError("Finish earlier games and resume the setup before recording this result.")
                game.update(status="completed", home_score=h, away_score=a,
                            completed_at=game["completed_at"] or now_iso())
            if kind in ("start", "score", "pitchers"):
                for side in ("home", "away"):
                    field = f"{side}_pitcher"
                    if field in action:
                        game[field] = text(action[field], "Pitcher", blank=True)
    else:
        raise RuleError("Unknown tournament action.")
    _, reset = reconcile(state, action.get("confirm_reset") is True)
    return reset


def validate_snapshot(state):
    """Validate structure AND tournament consistency before replacing live data."""
    try:
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise RuleError("Unsupported backup format.")
        expected = new_tournament(state, shuffle=False)
        if state["teams"] != expected["teams"]:
            raise RuleError("Invalid team identifiers in backup.")
        for group in "AB":
            if sorted(state["groups"][group]) != sorted(expected["groups"][group]):
                raise RuleError("Invalid group membership in backup.")
        expected["groups"] = deepcopy(state["groups"])
        # Reconstruct group assignments using the persisted randomized order.
        for group in "AB":
            ids = state["groups"][group]
            for n, (h, a) in enumerate([(0,1),(2,3),(0,2),(1,3),(3,0),(1,2)], 1):
                g = next(g for g in expected["games"] if g["id"] == f"{group}{n}")
                g.update(home=ids[h], away=ids[a])
        if not isinstance(state["games"], list) or len(state["games"]) != 27:
            raise RuleError("Backup must contain the full tournament schedule.")
        template = {g["id"]: g for g in expected["games"]}
        if {g["id"] for g in state["games"]} != set(template):
            raise RuleError("Invalid game identifiers in backup.")
        for game in state["games"]:
            base = template[game["id"]]
            if set(game) != set(base):
                raise RuleError("Invalid game fields in backup.")
            for key in ("phase", "setup", "sequence", "series", "number"):
                if game[key] != base[key]:
                    raise RuleError("Invalid schedule in backup.")
            if game["phase"] == "group" and (game["home"], game["away"]) != (base["home"], base["away"]):
                raise RuleError("Invalid group pairings in backup.")
            if game["status"] not in ("scheduled", "ongoing", "completed", "not_needed"):
                raise RuleError("Invalid game status in backup.")
            for key in ("home_pitcher", "away_pitcher"):
                text(game[key], "Pitcher", blank=True)
            for key in ("started_at", "completed_at"):
                if game[key] is not None:
                    timestamp(game[key])
            if game["started_at"] and game["completed_at"] and timestamp(game["started_at"]) > timestamp(game["completed_at"]):
                raise RuleError("A game cannot finish before it starts.")
            if game["status"] == "completed":
                integer(game["home_score"], "Home runs")
                integer(game["away_score"], "Away runs")
                if game["home_score"] == game["away_score"] or not game["completed_at"]:
                    raise RuleError("Completed games need an untied score and completion time.")
            elif game["home_score"] is not None or game["away_score"] is not None or game["completed_at"] is not None:
                raise RuleError("Unfinished games cannot contain final scores.")
            if game["status"] == "ongoing" and not game["started_at"]:
                raise RuleError("Ongoing games need a start time.")
            if game["status"] in ("scheduled", "not_needed") and game["started_at"]:
                raise RuleError("Unstarted games cannot have start times.")
        if set(state["pauses"]) != {"1", "2"}:
            raise RuleError("Invalid setup pauses.")
        for pause in state["pauses"].values():
            if pause is not None:
                if set(pause) != {"until"}:
                    raise RuleError("Invalid pause format.")
                if pause["until"]:
                    timestamp(pause["until"])
        for group, decision in state["ties"].items():
            if group not in "AB" or sorted(decision["order"]) != sorted(state["groups"][group]) or not isinstance(decision["signature"], str):
                raise RuleError("Invalid tie decision.")
        for series, decision in state["home_draws"].items():
            if series not in ("SF1", "SF2", "F") or decision["team"] not in {t["id"] for t in state["teams"]} or not isinstance(decision["signature"], str):
                raise RuleError("Invalid home decision.")
        timestamp(state["created_at"])
        checked = deepcopy(state)
        reconcile(checked)
        if checked["games"] != state["games"]:
            raise RuleError("Backup participants or series states do not match the recorded results.")
        for game in state["games"]:
            if game["status"] not in ("ongoing", "completed"):
                continue
            previous = deepcopy(state)
            previous["pauses"] = {"1": None, "2": None}
            probe = next(g for g in previous["games"] if g["id"] == game["id"])
            probe["status"] = "scheduled"
            if not ready(previous, probe, check_busy=False):
                raise RuleError("Backup has games played before their prerequisites.")
        ongoing = [g for g in state["games"] if g["status"] == "ongoing"]
        if len({g["setup"] for g in ongoing}) != len(ongoing):
            raise RuleError("Only one game can be ongoing on each setup.")
        if len({t for g in ongoing for t in (g["home"], g["away"])}) != 2*len(ongoing):
            raise RuleError("A team cannot play two ongoing games.")
        if any(g["status"] == "not_needed" and g["phase"] in ("group", "quarterfinal") for g in state["games"]):
            raise RuleError("Group games and quarterfinals cannot be skipped.")
        if set(state) != set(expected):
            raise RuleError("Invalid tournament fields in backup.")
        return deepcopy(state)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise RuleError("The backup is malformed; existing tournament data was not changed.") from None

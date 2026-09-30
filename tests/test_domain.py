from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from tournament.domain import (RuleError, mutate, ready, reconcile, schedule, series_winner,
                               standings, timestamp, validate_snapshot, view)

def game(state, id_):
    return next(g for g in state["games"] if g["id"] == id_)

def play(state, id_, winner=None, home=3, away=1):
    g = game(state, id_)
    if winner:
        home, away = (3, 1) if g["home"] == winner else (1, 3)
    mutate(state, dict(type="score", game=id_, home_score=home, away_score=away, home_pitcher="Cole", away_pitcher="Fried"))

def finish_groups(state):
    for g in state["games"]:
        if g["phase"] == "group":
            play(state, g["id"], min([g["home"], g["away"]]))

def resolve_draws(state):
    tables = standings(state)
    for group, table in tables.items():
        if table["unresolved"]:
            mutate(state, dict(type="tie", group=group, order=[r["team"] for r in table["rows"]]))
    pending, _ = reconcile(state)
    for p in pending:
        mutate(state, dict(type="home_draw", series=p["series"], team=p["teams"][0]))

def test_group_pairings_home_balance_and_ready(tournament):
    groups = [g for g in tournament["games"] if g["phase"] == "group"]
    assert len(groups) == 12
    assert len({frozenset((g["home"], g["away"])) for g in groups}) == 12
    assert set(Counter(t for g in groups for t in (g["home"], g["away"])).values()) == {3}
    assert set(Counter(g["home"] for g in groups).values()) <= {1,2}
    for g in groups:
        assert g["setup"] == (1 if g["id"].startswith("A") else 2)
    assert {g["id"] for g in groups if ready(tournament, g)} == {"A1", "B1"}
    with pytest.raises(RuleError):
        play(tournament, "A2")

def test_fixed_bracket_and_home(tournament):
    finish_groups(tournament)
    assert [(game(tournament,f"QF{i}")["home"],game(tournament,f"QF{i}")["away"]) for i in range(1,5)] == [("T1","T8"),("T2","T7"),("T6","T3"),("T5","T4")]
    assert not ready(tournament, game(tournament,"QF2"))
    for i in range(1,5): play(tournament,f"QF{i}")
    assert {game(tournament,"SF1-1")["home"],game(tournament,"SF1-1")["away"]} == {"T1","T2"}
    assert game(tournament,"SF1-1")["home"] == game(tournament,"SF1-2")["away"]
    assert game(tournament,"SF1-1")["home"] == game(tournament,"SF1-3")["home"]

@pytest.mark.parametrize("longest,total", [(False,23),(True,27)])
def test_complete_tournament_and_restore(tournament,longest,total):
    finish_groups(tournament)
    for i in range(1,5): play(tournament,f"QF{i}")
    for series,length in [("SF1",3),("SF2",3),("F",5)]:
        resolve_draws(tournament)
        opening = game(tournament, f"{series}-1")["home"]
        for n in range(1,length+1):
            g = game(tournament,f"{series}-{n}")
            if g["status"] == "not_needed": continue
            play(tournament, g["id"], None if longest else opening)
            validate_snapshot(tournament)
    assert len([g for g in tournament["games"] if g["status"] == "completed"]) == total
    assert series_winner(tournament,"F")
    assert view(tournament,10)["tournament"]["champion"] == series_winner(tournament,"F")
    assert validate_snapshot(tournament) == tournament

def test_three_way_tie_requires_manual_draw_and_invalidates_on_change(tournament):
    winners=["T1","T3","T3","T2","T1","T2"]
    for n,t in enumerate(winners,1): play(tournament,f"A{n}",t)
    table=standings(tournament)["A"]
    assert table["unresolved"] == [["T1","T2","T3"]]
    mutate(tournament,dict(type="tie",group="A",order=["T3","T1","T2","T4"]))
    assert [r["team"] for r in standings(tournament)["A"]["rows"]] == ["T3","T1","T2","T4"]
    play(tournament,"A1",home=5,away=3)
    assert standings(tournament)["A"]["rows"][0]["team"] == "T1"

def test_two_way_tie_uses_head_to_head_before_run_difference(tournament):
    winners=["T1","T3","T3","T2","T1","T2"]
    for n,t in enumerate(winners,1): play(tournament,f"A{n}",t)
    play(tournament,"A2",winner="T4")
    play(tournament,"A4",home=25,away=0)
    rows=standings(tournament)["A"]["rows"]
    assert rows[0]["team"] == "T1" and rows[1]["team"] == "T2"
    assert rows[0]["rd"] < rows[1]["rd"]

def test_group_correction_requires_downstream_confirmation(tournament):
    finish_groups(tournament); play(tournament,"QF1")
    candidate=deepcopy(tournament)
    with pytest.raises(RuleError) as error:
        play(candidate,"A1",winner="T2")
    assert "QF1" in error.value.affected
    mutate(tournament,dict(type="score",game="A1",home_score=1,away_score=3,confirm_reset=True))
    assert game(tournament,"QF1")["status"] == "scheduled"
    assert game(tournament,"QF1")["home"] == "T2"

def test_pitcher_and_nonseeding_score_corrections_preserve_playoffs(tournament):
    finish_groups(tournament); play(tournament,"QF1")
    original=deepcopy(game(tournament,"QF1"))
    mutate(tournament,dict(type="pitchers",game="A1",home_pitcher="New pitcher"))
    play(tournament,"A1",home=5,away=1)
    assert game(tournament,"QF1") == original

def test_schedule_rest_parallelism_and_early_finish(tournament):
    estimates=schedule(tournament,datetime(2030,9,30,9,tzinfo=timezone.utc))
    assert estimates["A1"]["estimated_start"] == estimates["B1"]["estimated_start"]
    assert timestamp(estimates["A2"]["estimated_start"])-timestamp(estimates["A1"]["estimated_end"]) == timedelta(minutes=5)
    assert timestamp(estimates["A3"]["estimated_start"])-timestamp(estimates["A2"]["estimated_end"]) == timedelta(minutes=10)
    assert timestamp(estimates["QF1"]["estimated_start"]) >= timestamp(estimates["B6"]["estimated_end"])+timedelta(minutes=10)
    finish_groups(tournament)
    for i in range(1,5): play(tournament,f"QF{i}")
    before=schedule(tournament)["F-1"]["estimated_start"]
    for series in ["SF1","SF2"]:
        home=game(tournament,series+"-1")["home"]
        play(tournament,series+"-1",home); play(tournament,series+"-2",home)
    assert game(tournament,"SF1-3")["status"] == "not_needed"
    assert schedule(tournament)["SF1-3"]["estimated_start"] is None
    assert timestamp(schedule(tournament)["F-1"]["estimated_start"]) < timestamp(before)

def test_overrun_pause_and_start_pitchers(tournament):
    mutate(tournament,dict(type="start",game="A1",home_pitcher="Cole"))
    assert game(tournament,"A1")["home_pitcher"] == "Cole"
    now=timestamp(game(tournament,"A1")["started_at"])+timedelta(minutes=40)
    estimates=schedule(tournament,now)
    assert estimates["A1"]["running_long"]
    assert timestamp(estimates["A2"]["estimated_start"]) >= now+timedelta(minutes=5)
    mutate(tournament,dict(type="pause",setup=2,paused=True,until=None))
    assert not ready(tournament,game(tournament,"B1"))
    assert schedule(tournament,now)["B1"]["estimated_start"] is None
    assert schedule(tournament,now)["F-1"]["estimated_start"] is None
    mutate(tournament,dict(type="pause",setup=2,paused=False))
    assert ready(tournament,game(tournament,"B1"))
    validate_snapshot(tournament)

@pytest.mark.parametrize("h,a", [(1,1),(-1,2),(True,2),(1.2,3),("3",2),(1000,0)])
def test_invalid_scores_rejected(tournament,h,a):
    with pytest.raises(RuleError): play(tournament,"A1",home=h,away=a)

def test_backup_rejects_broken_dependency_and_invalid_status(tournament):
    malformed=deepcopy(tournament)
    game(malformed,"A2").update(status="completed",home_score=3,away_score=1,completed_at="2030-09-30T10:00:00Z")
    with pytest.raises(RuleError):validate_snapshot(malformed)
    malformed=deepcopy(tournament);game(malformed,"A1")["home"]="T8"
    with pytest.raises(RuleError):validate_snapshot(malformed)
    malformed=deepcopy(tournament);game(malformed,"A1")["status"]="not_needed"
    with pytest.raises(RuleError):validate_snapshot(malformed)

def test_backup_with_completed_and_ongoing_same_field(tournament):
    play(tournament,"A1")
    mutate(tournament,dict(type="start",game="A2"))
    validate_snapshot(tournament)

def test_reopen_resets_later_games_only_after_confirmation(tournament):
    play(tournament,"A1");play(tournament,"A2")
    with pytest.raises(RuleError):mutate(deepcopy(tournament),dict(type="reopen",game="A1"))
    mutate(tournament,dict(type="reopen",game="A1",confirm_reset=True))
    assert game(tournament,"A2")["status"] == "scheduled"
    validate_snapshot(tournament)


def test_home_draw_needed_only_for_equal_group_records(tournament):
    finish_groups(tournament)
    for i in range(1,5): play(tournament,f"QF{i}")
    for series in ["SF1","SF2"]:
        home=game(tournament,series+"-1")["home"]
        play(tournament,series+"-1",home);play(tournament,series+"-2",home)
    pending,_=reconcile(tournament)
    assert pending==[{"series":"F","teams":["T1","T5"]}]
    assert not ready(tournament,game(tournament,"F-1"))
    mutate(tournament,dict(type="home_draw",series="F",team="T5"))
    assert game(tournament,"F-1")["home"]=="T5"
    assert game(tournament,"F-2")["home"]=="T1"
    assert ready(tournament,game(tournament,"F-1"))

def test_reopen_quarterfinal_resets_later_stage_on_other_field(tournament):
    finish_groups(tournament)
    for i in range(1,5): play(tournament,f"QF{i}")
    play(tournament,"SF2-1")
    candidate=deepcopy(tournament)
    with pytest.raises(RuleError) as error:
        mutate(candidate,dict(type="reopen",game="QF1"))
    assert "SF2-1" in error.value.affected
    mutate(tournament,dict(type="reopen",game="QF1",confirm_reset=True))
    assert game(tournament,"SF2-1")["status"]=="scheduled"
    validate_snapshot(tournament)

def test_early_actual_start_moves_future_estimates(tournament):
    mutate(tournament,dict(type="start",game="A1"))
    now=timestamp(game(tournament,"A1")["started_at"])
    assert timestamp(schedule(tournament,now)["A2"]["estimated_start"]) < timestamp(tournament["settings"]["start"])

def test_manual_order_cannot_repeat_a_team(tournament):
    for n,t in enumerate(["T1","T3","T3","T2","T1","T2"],1):play(tournament,f"A{n}",t)
    with pytest.raises(RuleError):
        mutate(tournament,dict(type="tie",group="A",order=["T1","T1","T3","T4"]))

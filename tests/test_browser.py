"""Real Chrome checks; skipped if Chrome is not installed. Uses an isolated test database."""
import os
from pathlib import Path
import shutil
import threading
import uuid
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

@pytest.fixture
def server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()

@pytest.fixture
def browser():
    executable = os.environ.get("BROWSER_EXECUTABLE") or shutil.which("google-chrome") or shutil.which("chromium")
    if not executable:
        pytest.skip("Set BROWSER_EXECUTABLE to run real-browser tests.")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox"])
        yield browser
        browser.close()

def test_setup_draw_scoring_and_mobile_layout(browser,server):
    page = browser.new_page(viewport={"width":1440,"height":1000})
    errors, external = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: external.append(request.url) if urlsplit(request.url).netloc != urlsplit(server).netloc else None)
    page.goto(server)
    expect(page.get_by_role("heading",name="Build your game day.")).to_be_visible()
    page.get_by_role("button",name="Draw partners").click()
    page.locator("textarea[name=top]").fill("\n".join(f"Top {i}" for i in range(8)))
    page.locator("textarea[name=other]").fill("\n".join(f"Other {i}" for i in range(8)))
    page.get_by_role("button",name="Draw partnerships").click()
    page.get_by_role("button",name="Use these teams").click()
    players = page.locator("input[name^=player-]").evaluate_all("(els)=>els.map(e=>e.value)")
    assert len(set(players)) == 16
    # Accepted draft survives a reload and never redraws.
    page.reload()
    expect(page.get_by_role("heading",name="Build your game day.")).to_be_visible()
    assert page.locator("input[name^=player-]").evaluate_all("(els)=>els.map(e=>e.value)") == players
    page.get_by_role("button",name="Preview tournament").click()
    page.get_by_role("button",name="Create tournament").click()
    expect(page.get_by_role("heading",name="Tournament overview")).to_be_visible()
    page.locator("button[data-game=A1]").click()
    page.locator("[name=home_pitcher]").fill("Gerrit Cole")
    page.locator("[name=away_pitcher]").fill("Max Fried")
    page.get_by_role("button",name="Start game",exact=True).click()
    expect(page.locator("dialog")).not_to_be_visible()
    page.locator("button[data-game=A1]").click()
    expect(page.locator("[name=home_pitcher]")).to_have_value("Gerrit Cole")
    page.locator("[name=home_score]").fill("4")
    page.locator("[name=away_score]").fill("2")
    page.get_by_role("button",name="Review result").click()
    page.get_by_role("button",name="Confirm & save result").click()
    expect(page.locator("dialog")).not_to_be_visible()
    state=page.request.get(server+"/api/state").json()
    g=next(g for g in state["tournament"]["games"] if g["id"]=="A1")
    assert g["status"]=="completed" and g["home_score"]==4 and g["home_pitcher"]=="Gerrit Cole"
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path="test-results/desktop.png",full_page=True)
    page.set_viewport_size({"width":390,"height":844})
    for route in ["dashboard","schedule","standings","bracket","teams","teams/"+g["home"],"settings"]:
        page.goto(server+"/#"+route)
        expect(page.locator("h1")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), route
    page.goto(server+"/#dashboard")
    page.screenshot(path="test-results/mobile.png",full_page=True)
    assert not errors
    assert not external
    page.close()

def test_open_form_survives_poll_and_conflict(browser,server,app,setup_data):
    store=app.extensions["store"]
    from tournament.domain import new_tournament
    store.change(0,str(uuid.uuid4()),{"type":"create"},lambda _:new_tournament(setup_data))
    page=browser.new_page()
    page.goto(server)
    page.locator("button[data-game=A1]").click()
    page.locator("[name=home_score]").fill("5")
    page.locator("[name=away_score]").fill("1")
    rev=page.request.get(server+"/api/state").json()["revision"]
    response=page.request.post(server+"/api/change",headers={"X-Tournament-Request":"1"},data={
        "revision":rev,"operation_id":str(uuid.uuid4()),
        "action":{"type":"score","game":"A1","home_score":3,"away_score":2,"home_pitcher":"Other pitcher"}})
    assert response.ok
    page.wait_for_timeout(5200)
    expect(page.locator("[name=home_score]")).to_have_value("5")
    page.get_by_role("button",name="Review result").click()
    page.on("dialog",lambda dialog:dialog.dismiss())
    page.get_by_role("button",name="Confirm & save result").click()
    expect(page.locator("dialog .error")).to_contain_text("Someone saved a change")
    final=page.request.get(server+"/api/state").json()
    assert next(g for g in final["tournament"]["games"] if g["id"]=="A1")["home_score"]==3
    page.close()

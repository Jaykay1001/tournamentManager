from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import uuid
from tournament.app import create_app

HEADERS={"X-Tournament-Request":"1"}
def change(client,action,revision=None,operation=None):
    if revision is None: revision=client.get("/api/state").json["revision"]
    return client.post("/api/change",json=dict(action=action,revision=revision,operation_id=operation or str(uuid.uuid4())),headers=HEADERS)

def test_create_score_restart_export_restore(app,setup_data):
    client=app.test_client()
    assert client.get("/api/state").json["tournament"] is None
    assert change(client,dict(type="create",tournament=setup_data)).status_code==200
    assert change(client,dict(type="start",game="A1",home_pitcher="Cole")).status_code==200
    assert change(client,dict(type="score",game="A1",home_score=4,away_score=2)).status_code==200
    snapshot=client.get("/api/export").json
    second=create_app(app.extensions["store"].directory).test_client()
    assert second.get("/api/export").json==snapshot
    assert change(client,dict(type="reset",confirmation="RESET")).status_code==200
    assert list((app.extensions["store"].directory/"backups").glob("*.json"))
    assert change(client,dict(type="restore",confirmation="REPLACE",snapshot=snapshot)).status_code==200
    assert client.get("/api/export").json==snapshot
    assert len(client.get("/api/history").json["entries"])==5

def test_stale_edit_and_idempotent_retry(app,setup_data):
    client=app.test_client();change(client,dict(type="create",tournament=setup_data))
    rev=client.get("/api/state").json["revision"]
    action=dict(type="score",game="A1",home_score=4,away_score=2)
    id_=str(uuid.uuid4())
    assert change(client,action,rev,id_).status_code==200
    assert change(client,action,rev,id_).status_code==200
    assert client.get("/api/state").json["revision"]==rev+1
    stale=change(client,dict(type="score",game="A1",home_score=1,away_score=3),rev)
    assert stale.status_code==409 and stale.json["latest"]["revision"]==rev+1

def test_simultaneous_phone_submissions(app,setup_data):
    client=app.test_client();change(client,dict(type="create",tournament=setup_data))
    rev=client.get("/api/state").json["revision"]
    def submit(id_):
        return change(app.test_client(),dict(type="score",game=id_,home_score=3,away_score=1),rev).status_code
    with ThreadPoolExecutor(2) as pool:
        codes=list(pool.map(submit,["A1","B1"]))
    assert sorted(codes)==[200,409]

def test_invalid_restore_is_atomic_and_cross_site_writes_denied(app,setup_data):
    client=app.test_client();change(client,dict(type="create",tournament=setup_data))
    before=client.get("/api/export").json
    broken=deepcopy(before);broken["games"][0]["home"]="T9"
    result=change(client,dict(type="restore",confirmation="REPLACE",snapshot=broken))
    assert result.status_code==400
    assert client.get("/api/export").json==before
    assert client.post("/api/change",json={},headers={**HEADERS,"Origin":"http://evil.example"}).status_code==403
    assert client.post("/api/change",json={}).status_code==403
    assert client.post("/api/change",json=[],headers=HEADERS).status_code==400

def test_local_assets_and_qr(app):
    client=app.test_client()
    response=client.get("/")
    assert response.status_code==200 and b"Schwaig Red Lions" in response.data
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/static/app.js").status_code==200
    assert client.get("/static/style.css").status_code==200
    qr=client.get("/api/qr.svg")
    assert qr.status_code==200 and qr.mimetype=="image/svg+xml" and b"<svg" in qr.data

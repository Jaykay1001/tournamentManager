import pytest
from tournament.app import create_app
from tournament.domain import new_tournament

@pytest.fixture
def setup_data():
    return dict(settings=dict(name="Friday Night Diamond", start="2030-09-30T10:00:00+00:00",
                              timezone="Europe/Berlin", game_minutes=25, break_minutes=5,
                              rest_minutes=10, setup_names=["Living Room", "Clubhouse"], pitchers=["Gerrit Cole", "Max Fried"]),
                teams=[dict(name=n, players=[f"Player {2*i+1}", f"Player {2*i+2}"], group="A" if i<4 else "B")
                       for i,n in enumerate(["Diamond Dogs", "Extra Innings", "The Sandlot", "Base Invaders", "Home Run Club", "Dugout Legends", "Pitch Please", "Bat Attitude"])])

@pytest.fixture
def tournament(setup_data):
    return new_tournament(setup_data, shuffle=False)

@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / "data")
    app.config["TESTING"] = True
    return app

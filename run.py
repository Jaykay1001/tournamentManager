import os
from waitress import serve
from tournament.app import create_app

if __name__ == "__main__":
    serve(create_app(), host=os.environ.get("TOURNAMENT_HOST", "0.0.0.0"),
          port=int(os.environ.get("TOURNAMENT_PORT", "8080")), threads=4)

"""Development entry point: `python app.py` (or `flask --app app run`)."""

from shiftcheck import create_app
from shiftcheck.db import init_db

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        init_db()
    if app.config["SECRET_KEY_GENERATED"]:
        print("[shiftcheck] SECRET_KEY is not set; using a temporary key (sessions reset on restart).")
    print(f"[shiftcheck] http://127.0.0.1:{app.config['PORT']}{app.config['URL_PREFIX']}/")
    app.run(host="0.0.0.0", port=app.config["PORT"], debug=app.config["DEBUG"])

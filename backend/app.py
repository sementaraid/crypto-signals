"""WSGI entry point: `gunicorn app:app`, or `python app.py` for local development."""

import logging
import os

from signals.api import create_app

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=os.environ.get("FLASK_DEBUG") == "1")

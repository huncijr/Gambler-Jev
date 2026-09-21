"""Gambler Jev: localhost blackjack website with Jev advice backend.

Run:
    pip install -r requirements.txt
    cp .env.example .env   # then put your TYPESAFE_API_KEY in .env
    python app.py
Open:
    http://127.0.0.1:5000
"""

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from jev import get_jev_advice, key_is_plausible  # noqa: E402

app = Flask(__name__, static_folder="static")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/favicon/<path:filename>")
def favicon(filename):
    return send_from_directory("favicon", filename)


@app.get("/favicon.ico")
def favicon_ico():
    return send_from_directory("favicon", "favicon.ico")


@app.get("/api/health")
def health():
    key = os.environ.get("TYPESAFE_API_KEY")
    return jsonify(
        {"ok": True, "jev": bool(key), "key_shape_ok": key_is_plausible(key)}
    )


@app.post("/api/jev-advice")
def jev_advice():
    data = request.get_json(silent=True) or {}
    player = data.get("player", [])
    dealer_up = data.get("dealer_up")

    if not isinstance(player, list) or len(player) == 0:
        return jsonify({"error": "player cards are required"}), 400
    try:
        for c in player:
            v = c["value"] if isinstance(c, dict) else c
            if v not in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"):
                raise ValueError(f"bad card value: {v!r}")
        if dealer_up is not None:
            v = dealer_up["value"] if isinstance(dealer_up, dict) else dealer_up
            if v not in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"):
                raise ValueError(f"bad dealer card value: {v!r}")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(get_jev_advice(player, dealer_up))


if __name__ == "__main__":
    # Localhost only: never expose the API key by binding to 0.0.0.0.
    app.run(host="127.0.0.1", port=5000, debug=False)

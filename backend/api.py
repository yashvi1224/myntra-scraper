"""
Flask API — wraps the Selenium+BS4 scraper for the web frontend.
"""

import json, os, tempfile
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

import sys
sys.path.insert(0, os.path.dirname(__file__))
from scraper import run as run_scraper

app = Flask(__name__, static_folder="../frontend")
CORS(app)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/scrape", methods=["POST"])
def scrape():
    if "file" not in request.files:
        return jsonify({"error": "No CSV file uploaded"}), 400

    csv_file = request.files["file"]
    delivery = request.form.get("delivery", "false").lower() == "true"

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        csv_file.save(tmp)
        tmp_path = tmp.name

    output_path = str(OUTPUT_DIR / "results.json")

    try:
        results = run_scraper(tmp_path, output_path, delivery_check=delivery)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(tmp_path)


@app.route("/results")
def get_results():
    f = OUTPUT_DIR / "results.json"
    return jsonify(json.loads(f.read_text(encoding="utf-8")) if f.exists() else [])


if __name__ == "__main__":
    app.run(debug=True, port=5000)

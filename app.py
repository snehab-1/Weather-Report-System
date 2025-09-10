from flask import Flask, request, jsonify, send_file, render_template, render_template_string, redirect, url_for, flash, make_response
import requests
import sqlite3
from datetime import datetime, timedelta, timezone
import io
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import base64
# from weasyprint import HTML

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import io

DB_PATH = "weather.db"
# OPEN_METEO_URL = "https://api.open-meteo.com/v1/meteoswiss"
# OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast?latitude=47.37&longitude=8.55&hourly=temperature_2m,relative_humidity_2m"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

app = Flask(__name__)
app.secret_key = "your-secret-key"

# --- Database helpers -----------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS weather (
        timestamp TEXT PRIMARY KEY,
        temperature REAL,
        humidity REAL,
        lat REAL,
        lon REAL
    )
    """)
    conn.commit()
    conn.close()

def upsert_weather_rows(rows, lat, lon):
    """
    rows: iterable of (timestamp_iso_utc_str, temperature, humidity)
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for ts, temp, hum in rows:
        # use INSERT OR REPLACE to upsert by timestamp
        cur.execute("""
            INSERT OR REPLACE INTO weather (timestamp, temperature, humidity, lat, lon)
            VALUES (?, ?, ?, ?, ?)
        """, (ts, temp, hum, lat, lon))
    conn.commit()
    conn.close()

def query_last_n_hours(n_hours=48):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=n_hours)
    cutoff_iso = cutoff.isoformat(timespec='seconds')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, temperature, humidity, lat, lon
        FROM weather
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    """, (cutoff_iso,))
    rows = cur.fetchall()
    conn.close()
    # return list of dicts
    return [
        {"timestamp": r[0], "temperature": r[1], "humidity": r[2], "lat": r[3], "lon": r[4]}
        for r in rows
    ]

# --- Utilities ------------------------------------------------------------
def iso_date(dt: datetime):
    return dt.strftime("%Y-%m-%d")

def parse_api_and_store(api_json, lat, lon):
    """
    api_json expected format with keys:
      hourly: { time: [...], temperature_2m: [...], relative_humidity_2m: [...] }
    Time strings are assumed to be ISO timestamps in UTC (or as returned).
    We'll convert to UTC ISO with timezone information if not present.
    """
    hourly = api_json.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    hums = hourly.get("relative_humidity_2m", [])

    rows = []
    for t, tmp, hum in zip(times, temps, hums):
        # normalize time strings to ISO with timezone UTC
        # Many Open-Meteo responses use "YYYY-MM-DDTHH:MM" w/o timezone if timezone=UTC param used.
        # We'll parse with fromisoformat and attach tzinfo=UTC if missing.
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            # fallback - try parse without T
            dt = datetime.strptime(t, "%Y-%m-%d %H:%M")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts_iso = dt.isoformat(timespec="seconds")  # e.g. '2025-09-10T12:00:00+00:00'
        rows.append((ts_iso, float(tmp) if tmp is not None else None, float(hum) if hum is not None else None))
    # store
    upsert_weather_rows(rows, lat, lon)
    return len(rows)

# --- Routes ---------------------------------------------------------------
@app.route("/")
def home():
    rows = query_last_n_hours(48)

    chart_b64 = None
    if rows:
        df = pd.DataFrame(rows)
        df['dt'] = pd.to_datetime(df['timestamp'])
        df.sort_values('dt', inplace=True)

        # Plot chart
        fig, ax1 = plt.subplots(figsize=(10, 4.5))
        ax1.plot(df['dt'], df['temperature'], label="Temperature (°C)", color="red")
        ax1.set_xlabel("Time (UTC)")
        ax1.set_ylabel("Temperature (°C)", color="red")
        ax1.tick_params(axis='y', labelcolor="red")

        ax2 = ax1.twinx()
        ax2.plot(df['dt'], df['humidity'], label="Humidity (%)", color="blue", linestyle="--")
        ax2.set_ylabel("Humidity (%)", color="blue")
        ax2.tick_params(axis='y', labelcolor="blue")

        fig.autofmt_xdate(rotation=30)
        plt.title("Weather Data (Last 48 Hours)")
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        buf.seek(0)
        chart_b64 = base64.b64encode(buf.read()).decode()

    return render_template("index.html", chart_b64=chart_b64)

@app.route("/chart", methods=["GET"])
def show_chart():
    rows = query_last_n_hours(48)
    if not rows:
        return "<h2>No data available. Please run /weather-report first.</h2>"

    df = pd.DataFrame(rows)
    df['dt'] = pd.to_datetime(df['timestamp'])
    df.sort_values('dt', inplace=True)

    # Plot with Matplotlib
    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.plot(df['dt'], df['temperature'], label="Temperature (°C)", color="red")
    ax1.set_xlabel("Time (UTC)")
    ax1.set_ylabel("Temperature (°C)", color="red")
    ax1.tick_params(axis='y', labelcolor="red")

    ax2 = ax1.twinx()
    ax2.plot(df['dt'], df['humidity'], label="Humidity (%)", color="blue", linestyle="--")
    ax2.set_ylabel("Humidity (%)", color="blue")
    ax2.tick_params(axis='y', labelcolor="blue")

    fig.autofmt_xdate(rotation=30)
    plt.title("Weather Data (Last 48 Hours)")
    fig.tight_layout()

    # Save chart as PNG in memory
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode()

    # Simple HTML template
    html = f"""
    <html>
    <head>
      <title>Weather Chart</title>
      <style>
        body {{ font-family: Arial, sans-serif; text-align: center; margin: 40px; }}
        h1 {{ color: #333; }}
        .meta {{ margin-bottom: 20px; font-size: 14px; color: #555; }}
        img {{ max-width: 90%; height: auto; border: 1px solid #ccc; box-shadow: 2px 2px 6px #aaa; }}
      </style>
    </head>
    <body>
      <h1>Weather Report</h1>
      <div class="meta">
        Location: lat={df['lat'].iloc[0]}, lon={df['lon'].iloc[0]}<br>
        Range: {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]} (UTC)
      </div>
      <img src='data:image/png;base64,{img_b64}' alt='Weather Chart'>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/weather-report", methods=["GET"])
def weather_report():
    """
    Fetch from Open-Meteo for the past 2 days (48 hours) for given lat & lon,
    store into sqlite DB, and return summary JSON.
    Example:
      GET /weather-report?lat=47.37&lon=8.55
    """
    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))
    if not lat or not lon:
        return jsonify({"error": "Please provide lat and lon query parameters"}), 400

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except ValueError:
        return jsonify({"error": "Invalid lat/lon format"}), 400

    # compute date range for "past 2 days" -> use today and 2 days back inclusive
    # Open-Meteo accepts start_date and end_date as YYYY-MM-DD (calendar days).
    now_utc = datetime.now(timezone.utc)
    start_dt = now_utc - timedelta(days=2)
    start_date = iso_date(start_dt)
    end_date = iso_date(now_utc)
    params = {
        "latitude": lat_f,
        "longitude": lon_f,
        "hourly": "temperature_2m,relative_humidity_2m",
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "UTC"
    }

    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return jsonify({"error": "Failed to fetch Open-Meteo API", "details": str(e)}), 502

    api_json = r.json()

    count = parse_api_and_store(api_json, lat_f, lon_f)

    return jsonify({
        "status": "success",
        "message": "Fetched and stored weather data",
        "rows_stored": count,
        "range": {"start_date": start_date, "end_date": end_date},
        "lat": lat_f,
        "lon": lon_f
    })

@app.route("/export/excel", methods=["GET"])
def export_excel():
    rows = query_last_n_hours(48)
    if not rows:
        return jsonify({"error": "No data for the last 48 hours. Run /weather-report first."}), 404

    df = pd.DataFrame(rows)
    df = df[["timestamp", "temperature", "humidity"]]
    df.rename(columns={
        "temperature": "temperature_2m",
        "humidity": "relative_humidity_2m"
    }, inplace=True)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="last_48h")
    out.seek(0)

    filename = f"weather_last_48h_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.xlsx"
    return send_file(
        out,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/export/pdf", methods=["GET"])
def export_pdf():
    rows = query_last_n_hours(48)
    if not rows:
        return jsonify({"error": "No data for the last 48 hours. Run /weather-report first."}), 404

    df = pd.DataFrame(rows)
    df['dt'] = pd.to_datetime(df['timestamp'])
    df.sort_values('dt', inplace=True)

    lat = df['lat'].iloc[0]
    lon = df['lon'].iloc[0]
    start_ts = df['timestamp'].iloc[0]
    end_ts = df['timestamp'].iloc[-1]

    # Generate chart with Matplotlib
    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.plot(df['dt'], df['temperature'], label="Temperature (°C)")
    ax1.set_xlabel("Time (UTC)")
    ax1.set_ylabel("Temperature (°C)")

    ax2 = ax1.twinx()
    ax2.plot(df['dt'], df['humidity'], label="Relative Humidity (%)", linestyle="--", color="orange")
    ax2.set_ylabel("Relative Humidity (%)")

    ax1.legend(loc="upper left")
    fig.autofmt_xdate(rotation=30)

    img_buffer = io.BytesIO()
    plt.tight_layout()
    fig.savefig(img_buffer, format="png", dpi=150)
    plt.close(fig)
    img_buffer.seek(0)

    # Build PDF
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Weather Report", styles['Title']))
    elements.append(Paragraph(f"Location: lat={lat}, lon={lon}", styles['Normal']))
    elements.append(Paragraph(f"Range: {start_ts} → {end_ts} (UTC)", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Add chart image
    img = Image(img_buffer, width=500, height=250)
    elements.append(img)

    doc.build(elements)

    pdf_buffer.seek(0)
    filename = f"weather_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.pdf"
    return send_file(pdf_buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

# --- App startup ----------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

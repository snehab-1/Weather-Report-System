# 🌦 Weather Report System

A small Flask backend service that fetches **time-series weather data** from the [Open-Meteo API](https://open-meteo.com/) and generates:

- 📊 An interactive web dashboard with a chart  
- 📑 An Excel export (`.xlsx`)  
- 📄 A PDF report with chart  

---

## 🚀 Features

- Fetch last **48 hours** of hourly temperature & humidity data  
- Save results to **SQLite database**  
- Web dashboard (`/`) with:
  - Fetch Weather Data button (AJAX, no page reload)  
  - Auto-updating chart (temperature & humidity vs time)  
  - Export buttons (Excel + PDF)  
- REST API endpoints for programmatic access:
  - `GET /weather-report?lat={lat}&lon={lon}`
  - `GET /export/excel`
  - `GET /export/pdf`

---

## 🛠 Installation

```bash
git clone https://github.com/snehab-1/weather-report-system.git
cd weather-report-system
pip install -r requirements.txt

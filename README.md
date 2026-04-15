# 🎯 Discord Link Hunter — Setup Guide

A local web app that scrapes Reddit, Disboard, Discord.me, and Twitter/X (via Nitter) for trading-related Discord server invite links.

---

## ✅ Requirements

- **Python 3.8 or higher** — [Download here](https://www.python.org/downloads/)
- Internet connection
- A modern browser (Chrome, Firefox, Edge)

---

## 🚀 Step-by-Step Setup

### Step 1 — Verify Python is installed

Open your **Terminal** (Mac/Linux) or **Command Prompt / PowerShell** (Windows) and run:

```bash
python --version
```

You should see something like `Python 3.11.2`. If you get an error, install Python from https://www.python.org/downloads/ and make sure to check **"Add Python to PATH"** during installation on Windows.

---

### Step 2 — Navigate to the project folder

Unzip the downloaded file, then in your terminal navigate into it:

```bash
cd path/to/discord_hunter
```

**Example on Windows:**
```bash
cd C:\Users\YourName\Downloads\discord_hunter
```

**Example on Mac/Linux:**
```bash
cd ~/Downloads/discord_hunter
```

---

### Step 3 — Create a virtual environment (recommended)

This keeps the app's packages separate from your system Python.

```bash
python -m venv venv
```

Then activate it:

**Windows:**
```bash
venv\Scripts\activate
```

**Mac / Linux:**
```bash
source venv/bin/activate
```

You'll see `(venv)` appear in your terminal prompt — that means it worked.

---

### Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

This only installs **Flask** — a lightweight web framework. No heavy dependencies.

---

### Step 5 — Run the app

```bash
python app.py
```

You should see:

```
🎯 Discord Link Hunter started!
👉  Open http://127.0.0.1:5000 in your browser
```

---

### Step 6 — Open in browser

Open your browser and go to:

```
http://127.0.0.1:5000
```

The Discord Link Hunter UI will load. Configure your sources and click **Start Hunting**!

---

## 🖥️ How to Use

| Setting | Description |
|---|---|
| **Sources** | Check which platforms to scrape. Reddit + Disboard are most reliable. |
| **Depth** | Quick (~2 min) for a fast test. Deep (~20 min) for maximum results. |
| **Custom Keywords** | Type a keyword and press Enter to add it to the search. |
| **Custom Subreddits** | Add specific subreddits like `TradingView` or `Scalping`. |

### During a scrape:
- The **Activity Log** shows live progress
- **Discovered Servers** table fills in real-time
- Use the **Filter** box to search results by code, source, or context
- Download results via **CSV** or **JSON** buttons

---

## 🔄 Will I Always Get Fresh Results?

**Mostly yes.** Here's how to maximise new finds:

1. **Run it on different days** — Reddit gets new posts daily with new invites
2. **Rotate keywords** — Try `"algo trading discord"`, `"prop firm discord"`, `"funded trader discord"` etc.
3. **Add niche subreddits** — e.g. `r/Forex`, `r/FuturesTrading`, `r/Scalping`
4. **Use Deep mode** — scans more pages and more posts per subreddit
5. Results are **deduplicated per session** — running again tomorrow will yield new links that were posted since your last run

Popular servers will appear repeatedly across sources — that's normal. The filter helps you quickly spot new ones.

---

## 💾 Saved Results

Every completed scrape is **auto-saved** to the `results/` folder as a JSON file named with the timestamp, e.g.:

```
results/discord_links_20240615_143022.json
```

You can also manually export from the UI as CSV or JSON at any time.

---

## ⚠️ Troubleshooting

| Problem | Fix |
|---|---|
| `python: command not found` | Use `python3` instead of `python`, or reinstall Python with PATH enabled |
| `ModuleNotFoundError: flask` | Run `pip install -r requirements.txt` again |
| Port 5000 already in use | Edit the last line of `app.py` — change `port=5000` to `port=5001`, then visit `http://127.0.0.1:5001` |
| App starts but browser shows error | Wait 2–3 seconds and refresh — Flask needs a moment to fully start |
| Twitter source finds nothing | Nitter public mirrors go offline sometimes — try again later or uncheck Twitter |
| `(venv)` disappeared from terminal | Run `source venv/bin/activate` (Mac/Linux) or `venv\Scripts\activate` (Windows) again |

---

## 🛑 Stopping the App

In your terminal, press:

```
Ctrl + C
```

This stops the Flask server. Your results are already saved in the `results/` folder.

---

## 📁 Project Structure

```
discord_hunter/
├── app.py              ← Main application (run this)
├── requirements.txt    ← Python dependencies
├── README.md           ← This guide
├── templates/
│   └── index.html      ← Web UI
└── results/            ← Auto-saved scrape results (created on first run)
```

---

*Built with Flask + Python standard library. No API keys required.*

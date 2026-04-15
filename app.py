import os, re, json, time, random, logging, datetime, threading, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, Response, render_template

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scrape_status = {
    "running": False, "progress": [], "results": [],
    "seen_codes": set(), "error": None,
    "_lock": threading.Lock(),
}

DISCORD_RE = re.compile(
    r'discord(?:app)?\.com/invite/([A-Za-z0-9\-_]{2,50})'
    r'|discord\.gg/([A-Za-z0-9\-_]{2,50})', re.I)

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
]

DISBOARD_TAGS    = ["trading","forex","crypto-trading","stocks","day-trading","options-trading",
                    "investing","signals","scalping","swing-trading","cryptocurrency","bitcoin"]
DISCORD_ME_TAGS  = ["trading","crypto","forex","stocks","investing","signals","finance"]
DISCORDS_COM_TAGS= ["trading","forex","crypto","stocks","investing","finance","signals"]
DISCORD_BOATS_T  = ["trading","crypto","forex","stocks","investing"]
TOPGG_TAGS       = ["trading","forex","crypto","stocks","investing","finance","signals"]
DISCORDSVRS_TAGS = ["trading","forex","crypto","stocks","investing","finance"]
FINDDISCORD_TAGS = ["trading","forex","crypto","stocks","finance","investing"]

SUBREDDITS = ["Forex","Daytrading","stocks","investing","Cryptotrading","algotrading",
              "options","StockMarket","pennystocks","Wallstreetbets","cryptocurrency",
              "Bitcoin","Trading","FuturesTrading","scalping","technicalanalysis",
              "thetagang","swingtrading","forex_trading","CryptoMarkets","SatoshiStreetBets"]

DDG_QUERIES = [
    "discord.gg forex trading","discord.gg stocks trading server","discord.gg crypto signals",
    "discord.gg options trading","discord.gg futures trading","discord.gg swing trading",
    "discord.gg penny stocks","discord.gg algorithmic trading","discord.gg bitcoin signals",
    "discord.gg day trading","discord.gg scalping forex","discord.gg crypto pump signals",
]

BING_QUERIES = [
    '"discord.gg" forex trading free','"discord.gg" stocks signals',
    '"discord.gg" day trading community','"discord.gg" swing trading alerts',
    '"discord.gg" options trading signals','"discord.gg" futures trading',
    '"discord.gg" crypto signals','"discord.gg" penny stocks alerts',
    '"discord.gg" algorithmic trading','"discord.gg" bitcoin ethereum signals',
]

NITTER_INSTANCES = ["nitter.poast.org","nitter.privacydev.net","nitter.cz","nitter.1d4.us"]
NITTER_QUERIES   = ["forex discord.gg","crypto trading discord.gg","stocks discord.gg",
                    "trading signals discord.gg","day trading discord.gg","options discord.gg"]
STOCKTWITS_SYMS  = ["FOREX","SPY","QQQ","TSLA","AAPL","BTC.X","ETH.X","GC_F","CL_F","ES_F"]

# ── Core helpers ──────────────────────────────────────────────────

def extract_codes(text):
    return list({(m.group(1) or m.group(2))
                 for m in DISCORD_RE.finditer(text or "")
                 if (m.group(1) or m.group(2))})

def log(msg, level="info"):
    with scrape_status["_lock"]:
        scrape_status["progress"].append({"msg": msg, "level": level, "ts": time.time()})

def add_result(code, source, context=""):
    if not code or len(code) < 3 or len(code) > 50:
        return False
    with scrape_status["_lock"]:
        if code in scrape_status["seen_codes"]:
            return False
        scrape_status["seen_codes"].add(code)
        scrape_status["results"].append({
            "code": code, "url": f"https://discord.gg/{code}",
            "source": source, "context": context[:120],
            "found_at": datetime.datetime.now().strftime("%H:%M:%S"),
        })
    return True

def add_many(codes, source, context=""):
    return sum(1 for c in codes if add_result(c, source, context))

def get(url, headers=None, timeout=10, retries=2):
    h = {"User-Agent": random.choice(UAS),
         "Accept": "text/html,application/xhtml+xml,application/json,*/*",
         "Accept-Language": "en-US,en;q=0.9"}
    if headers: h.update(headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(8 * (attempt + 1))
            elif e.code in (403, 404, 410): return None
            else: time.sleep(2)
        except Exception: time.sleep(1)
    return None

def get_json(url):
    raw = get(url, headers={"Accept": "application/json"})
    if not raw: return None
    try: return json.loads(raw)
    except: return None

def running(): return scrape_status["running"]

# ── Scrapers ──────────────────────────────────────────────────────

def scrape_disboard(pages=3):
    found = 0
    for tag in DISBOARD_TAGS:
        if not running(): break
        for page in range(1, pages + 1):
            html = get(f"https://disboard.org/servers/tag/{tag}?page={page}&sort=-member_count",
                       headers={"Referer": "https://disboard.org/"})
            if html:
                pat = re.compile(r'href=["\']https?://discord(?:app)?\.com/invite/([A-Za-z0-9\-_]+)["\']'
                                 r'|href=["\']https?://discord\.gg/([A-Za-z0-9\-_]+)["\']', re.I)
                for m in pat.finditer(html):
                    code = m.group(1) or m.group(2)
                    if add_result(code, f"Disboard:{tag}", f"p{page}"): found += 1
            time.sleep(random.uniform(0.8, 1.5))
    log(f"  Disboard → {found}")
    return found

def scrape_discord_me(pages=5):
    found = 0
    for tag in DISCORD_ME_TAGS:
        if not running(): break
        for page in range(1, pages + 1):
            html = get(f"https://discord.me/servers/{page}?keyword={tag}")
            if html: found += add_many(extract_codes(html), f"Discord.me:{tag}", f"p{page}")
            time.sleep(random.uniform(0.8, 1.5))
    log(f"  Discord.me → {found}")
    return found

def scrape_discords_com(pages=3):
    found = 0
    for tag in DISCORDS_COM_TAGS:
        if not running(): break
        for page in range(1, pages + 1):
            html = get(f"https://discords.com/servers/{tag}?page={page}")
            if html:
                found += add_many(extract_codes(html), f"Discords.com:{tag}", f"p{page}")
                for m in re.finditer(r'data-invite=["\']([A-Za-z0-9\-_]{2,50})["\']', html, re.I):
                    if add_result(m.group(1), f"Discords.com:{tag}", f"p{page}"): found += 1
            time.sleep(random.uniform(0.8, 1.5))
    log(f"  Discords.com → {found}")
    return found

def scrape_discord_boats(pages=3):
    found = 0
    for tag in DISCORD_BOATS_T:
        if not running(): break
        for page in range(1, pages + 1):
            html = get(f"https://discord.boats/tag/{tag}?page={page}")
            if html: found += add_many(extract_codes(html), f"Discord.boats:{tag}", f"p{page}")
            time.sleep(random.uniform(0.8, 1.5))
    log(f"  Discord.boats → {found}")
    return found

def scrape_topgg(pages=3):
    found = 0
    for tag in TOPGG_TAGS:
        if not running(): break
        for page in range(1, pages + 1):
            html = get(f"https://top.gg/servers/tag/{tag}?page={page}")
            if html: found += add_many(extract_codes(html), f"Top.gg:{tag}", f"p{page}")
            time.sleep(random.uniform(1, 2))
    log(f"  Top.gg → {found}")
    return found

def scrape_discordservers_com(pages=3):
    found = 0
    for tag in DISCORDSVRS_TAGS:
        if not running(): break
        for page in range(1, pages + 1):
            html = get(f"https://discordservers.com/browse/{tag}/1/{page}")
            if html: found += add_many(extract_codes(html), f"DiscordServers.com:{tag}", f"p{page}")
            time.sleep(random.uniform(0.8, 1.5))
    log(f"  DiscordServers.com → {found}")
    return found

def scrape_find_discord(pages=3):
    found = 0
    for tag in FINDDISCORD_TAGS:
        if not running(): break
        for page in range(1, pages + 1):
            html = get(f"https://find-discord.com/category/{tag}?page={page}")
            if html: found += add_many(extract_codes(html), f"Find-Discord.com:{tag}", f"p{page}")
            time.sleep(random.uniform(0.8, 1.5))
    log(f"  Find-Discord.com → {found}")
    return found

def scrape_duckduckgo(limit=None):
    found = 0
    queries = DDG_QUERIES[:limit] if limit else DDG_QUERIES
    for q in queries:
        if not running(): break
        html = get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}")
        if html: found += add_many(extract_codes(html), f"DDG:{q[:40]}", q)
        time.sleep(random.uniform(2, 3.5))
    log(f"  DuckDuckGo → {found}")
    return found

def scrape_bing(limit=None):
    found = 0
    queries = BING_QUERIES[:limit] if limit else BING_QUERIES
    for q in queries:
        if not running(): break
        html = get(f"https://www.bing.com/search?q={urllib.parse.quote(q)}&count=50")
        if html: found += add_many(extract_codes(html), f"Bing:{q[:40]}", q)
        time.sleep(random.uniform(2, 3.5))
    log(f"  Bing → {found}")
    return found

def _reddit_sub(sub, limit=100):
    found = 0
    for sort in ["new", "hot"]:
        data = get_json(f"https://www.reddit.com/r/{sub}/{sort}.json?limit={limit}")
        if not data: continue
        posts = data.get("data", {}).get("children", [])
        for p in posts:
            pd = p.get("data", {})
            text = f"{pd.get('title','')} {pd.get('selftext','')} {pd.get('url','')}"
            found += add_many(extract_codes(text), f"Reddit r/{sub}", pd.get("title","")[:80])
        for p in posts[:10]:
            pd = p.get("data", {}); pl = pd.get("permalink", "")
            if not pl: continue
            cdata = get_json(f"https://www.reddit.com{pl}.json?limit=30")
            if cdata and isinstance(cdata, list):
                try:
                    for c in cdata[1]["data"]["children"]:
                        body = c.get("data", {}).get("body", "")
                        found += add_many(extract_codes(body), f"Reddit r/{sub} comments", body[:80])
                except: pass
            time.sleep(0.4)
        time.sleep(random.uniform(1.5, 2.5))
    return found

def scrape_reddit(subs, keywords, pages=2):
    found = 0
    for sub in subs:
        if not running(): break
        found += _reddit_sub(sub)
        time.sleep(random.uniform(1, 2))
    for kw in keywords:
        if not running(): break
        data = get_json(f"https://www.reddit.com/search.json?q={urllib.parse.quote(kw)}&sort=new&limit=100")
        if data:
            for p in data.get("data", {}).get("children", []):
                pd = p.get("data", {})
                text = f"{pd.get('title','')} {pd.get('selftext','')} {pd.get('body','')} {pd.get('url','')}"
                found += add_many(extract_codes(text), f"Reddit search:{kw[:30]}", pd.get("title","")[:80])
        time.sleep(random.uniform(2, 3))
    log(f"  Reddit → {found}")
    return found

def scrape_nitter(limit=None):
    found = 0
    queries = NITTER_QUERIES[:limit] if limit else NITTER_QUERIES
    for q in queries:
        if not running(): break
        encoded = urllib.parse.quote(q)
        for inst in NITTER_INSTANCES:
            html = get(f"https://{inst}/search?q={encoded}&f=tweets", timeout=8)
            if html:
                codes = extract_codes(html)
                n = add_many(codes, f"Twitter/Nitter:{q[:30]}", q)
                found += n
                if codes: log(f"  Nitter [{inst}] '{q}': {len(codes)} links")
                break
            time.sleep(0.5)
        time.sleep(random.uniform(1.5, 3))
    log(f"  Twitter/Nitter → {found}")
    return found

def scrape_4chan_biz():
    found = 0
    data = get_json("https://a.4cdn.org/biz/catalog.json")
    if not data: return 0
    thread_ids = []
    for page in data:
        for t in page.get("threads", []):
            com = t.get("com", "") + " " + t.get("sub", "")
            found += add_many(extract_codes(com), "4chan /biz/ catalog", com[:80])
            if any(k in com.lower() for k in ["discord","forex","trading","crypto","stocks","signals"]):
                thread_ids.append(t["no"])
    log(f"  4chan /biz/: {min(len(thread_ids),25)} threads")
    for tid in thread_ids[:25]:
        if not running(): break
        tdata = get_json(f"https://a.4cdn.org/biz/thread/{tid}.json")
        if tdata:
            for post in tdata.get("posts", []):
                text = post.get("com", "") + " " + post.get("sub", "")
                found += add_many(extract_codes(text), f"4chan /biz/ t:{tid}", text[:80])
        time.sleep(0.6)
    log(f"  4chan /biz/ → {found}")
    return found

def scrape_stocktwits():
    found = 0
    for sym in STOCKTWITS_SYMS:
        if not running(): break
        data = get_json(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json?limit=30")
        if data:
            for msg in data.get("messages", []):
                body = msg.get("body", "")
                found += add_many(extract_codes(body), f"StockTwits ${sym}", body[:80])
        time.sleep(1)
    log(f"  StockTwits → {found}")
    return found

def scrape_tradingview():
    found = 0
    for term in ["forex","stocks","crypto","signals","daytrading"]:
        if not running(): break
        html = get(f"https://www.tradingview.com/scripts/?script_type=study&search={term}")
        if html: found += add_many(extract_codes(html), f"TradingView:{term}", "")
        time.sleep(1.5)
    log(f"  TradingView → {found}")
    return found

def scrape_hive():
    found = 0
    for tag in ["forex","trading","crypto","stocks","cryptocurrency","daytrading"]:
        if not running(): break
        html = get(f"https://hive.blog/trending/{tag}")
        if html: found += add_many(extract_codes(html), f"Hive.blog:{tag}", "")
        time.sleep(1.5)
    log(f"  Hive.blog → {found}")
    return found

def scrape_youtube():
    found = 0
    terms = ["forex trading discord server free","stock trading discord community",
             "crypto signals discord free","day trading discord server","options trading discord"]
    for term in terms:
        if not running(): break
        html = get(f"https://www.youtube.com/results?search_query={urllib.parse.quote(term)}")
        if html: found += add_many(extract_codes(html), f"YouTube:{term[:40]}", term)
        time.sleep(2)
    log(f"  YouTube → {found}")
    return found

def scrape_medium():
    found = 0
    terms = ["discord trading server forex","discord crypto signals free","discord stock trading"]
    for term in terms:
        if not running(): break
        html = get(f"https://www.bing.com/search?q={urllib.parse.quote('site:medium.com '+term+' discord.gg')}&count=20")
        if html:
            for mu in list(dict.fromkeys(re.findall(r'href=["\']https?://medium\.com/[^\s"\'<>]+["\']', html)))[:5]:
                mhtml = get(mu.strip('"\''), timeout=12)
                if mhtml: found += add_many(extract_codes(mhtml), f"Medium:{term[:30]}", mu[:80])
                time.sleep(1)
        time.sleep(3)
    log(f"  Medium → {found}")
    return found

def scrape_github():
    found = 0
    for term in ["discord.gg trading forex","discord.gg forex signals","discord.gg stocks trading",
                 "discord.gg crypto signals","discord invite trading"]:
        if not running(): break
        html = get(f"https://github.com/search?q={urllib.parse.quote(term)}&type=code",
                   headers={"Accept": "text/html"})
        if html: found += add_many(extract_codes(html), f"GitHub:{term[:40]}", "")
        time.sleep(4)
    log(f"  GitHub → {found}")
    return found

def scrape_pastebin():
    found = 0
    for term in ["discord.gg forex","discord.gg trading","discord.gg stocks","discord.gg crypto signals"]:
        if not running(): break
        html = get(f"https://www.bing.com/search?q={urllib.parse.quote('site:pastebin.com '+term)}&count=20")
        if html:
            for pid in list(dict.fromkeys(re.findall(r'href=["\']https?://pastebin\.com/([A-Za-z0-9]+)["\']', html)))[:8]:
                raw = get(f"https://pastebin.com/raw/{pid}")
                if raw: found += add_many(extract_codes(raw), f"Pastebin:{pid}", "")
                time.sleep(1)
        time.sleep(3)
    log(f"  Pastebin → {found}")
    return found

# ── Parallel orchestrator ─────────────────────────────────────────

# (fn, args_factory(pages, subs, keywords))
SCRAPERS = {
    "disboard":       (scrape_disboard,         lambda p,s,k: (p,)),
    "discordme":      (scrape_discord_me,        lambda p,s,k: (p,)),
    "discords_com":   (scrape_discords_com,      lambda p,s,k: (p,)),
    "discord_boats":  (scrape_discord_boats,     lambda p,s,k: (p,)),
    "topgg":          (scrape_topgg,             lambda p,s,k: (p,)),
    "discordservers": (scrape_discordservers_com,lambda p,s,k: (p,)),
    "find_discord":   (scrape_find_discord,      lambda p,s,k: (p,)),
    "duckduckgo":     (scrape_duckduckgo,        lambda p,s,k: (None,)),
    "bing":           (scrape_bing,              lambda p,s,k: (None,)),
    "reddit":         (scrape_reddit,            lambda p,s,k: (s, k, p)),
    "twitter":        (scrape_nitter,            lambda p,s,k: (None,)),
    "fourchan":       (scrape_4chan_biz,          lambda p,s,k: ()),
    "stocktwits":     (scrape_stocktwits,         lambda p,s,k: ()),
    "tradingview":    (scrape_tradingview,        lambda p,s,k: ()),
    "hive":           (scrape_hive,              lambda p,s,k: ()),
    "youtube":        (scrape_youtube,           lambda p,s,k: ()),
    "medium":         (scrape_medium,            lambda p,s,k: ()),
    "github":         (scrape_github,            lambda p,s,k: ()),
    "pastebin":       (scrape_pastebin,          lambda p,s,k: ()),
}

def run_scrape(config):
    # NOTE: seen_codes is intentionally NOT reset here so servers found in
    # previous runs are never surfaced again. Only /api/clear wipes it.
    with scrape_status["_lock"]:
        scrape_status.update(running=True, results=[], progress=[], error=None)
    try:
        sources  = config.get("sources", list(SCRAPERS.keys()))
        keywords = config.get("keywords") or [
            "discord.gg forex","discord.gg trading","discord.gg crypto signals","discord.gg stocks"]
        subs     = config.get("subreddits") or SUBREDDITS
        pages    = {"quick": 1, "normal": 3, "deep": 7}.get(config.get("depth","normal"), 3)

        active = [s for s in sources if s in SCRAPERS]
        log(f"🚀 Running {len(active)} scrapers in parallel (12 threads)…")

        with ThreadPoolExecutor(max_workers=12) as ex:
            futures = {ex.submit(fn, *arg_f(pages, subs, keywords)): sid
                       for sid in active for fn, arg_f in [SCRAPERS[sid]]}
            for fut in as_completed(futures):
                sid = futures[fut]
                try: fut.result()
                except Exception as e: log(f"  ⚠ {sid}: {e}", "warning")

        total = len(scrape_status["results"])
        log(f"✅ Done! {total} unique Discord server links found.", "info")
        save_results()
    except Exception as e:
        scrape_status["error"] = str(e)
        log(f"❌ Fatal error: {e}", "error")
    finally:
        scrape_status["running"] = False

def save_results():
    os.makedirs("results", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"results/discord_links_{ts}.json"
    with open(path, "w") as f:
        json.dump(scrape_status["results"], f, indent=2)
    log(f"💾 Saved → {path}")

# ── Flask routes ──────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")
@app.route("/api/start", methods=["POST"])
def start():
    if scrape_status["running"]: return jsonify({"error": "Already running"}), 400
    cfg = request.get_json(silent=True) or {}
    threading.Thread(target=run_scrape, args=(cfg,), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/api/stop", methods=["POST"])
def stop():
    scrape_status["running"] = False
    return jsonify({"status": "stopped"})

@app.route("/api/status")
def status():
    return jsonify({
        "running": scrape_status["running"],
        "count": len(scrape_status["results"]),
        "progress": scrape_status["progress"][-100:],
        "error": scrape_status["error"],
    })

@app.route("/api/results")
def results():
    return jsonify(scrape_status["results"])

@app.route("/api/export")
def export():
    fmt = request.args.get("fmt","json"); data = scrape_status["results"]
    if fmt == "csv":
        lines = ["code,url,source,context,found_at"] + [
            f'"{r["code"]}","{r["url"]}","{r["source"].replace(chr(34),"")}","{r["context"].replace(chr(34),"")}","{r["found_at"]}"'
            for r in data]
        return Response("\n".join(lines), mimetype="text/csv",
                        headers={"Content-Disposition":"attachment;filename=discord_links.csv"})
    return Response(json.dumps(data, indent=2), mimetype="application/json",
                    headers={"Content-Disposition":"attachment;filename=discord_links.json"})

@app.route("/api/clear", methods=["POST"])
def clear():
    with scrape_status["_lock"]:
        scrape_status["results"] = []
        scrape_status["seen_codes"] = set()   # full history wipe — next run starts fresh
        scrape_status["progress"] = []
        scrape_status["error"] = None
    return jsonify({"status": "cleared"})

if __name__ == "__main__":
    os.makedirs("results", exist_ok=True)
    print("\n🎯 Discord Link Hunter v3 — PARALLEL MODE")
    print("👉  http://127.0.0.1:5000\n")
    app.run(debug=False, port=5000, threaded=True)
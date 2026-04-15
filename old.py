import os
import re
import json
import time
import random
import logging
import datetime
import threading
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Global state ──────────────────────────────────────────────────
scrape_status = {
    "running": False,
    "progress": [],
    "results": [],
    "seen_codes": set(),
    "error": None,
    "_lock": threading.Lock(),
}

DISCORD_PATTERN = re.compile(
    r'discord(?:app)?\.com/invite/([A-Za-z0-9\-_]{2,50})'
    r'|discord\.gg/([A-Za-z0-9\-_]{2,50})',
    re.IGNORECASE
)

TRADING_SUBREDDITS = [
    "Forex","Daytrading","stocks","investing","Cryptotrading","algotrading",
    "options","StockMarket","pennystocks","Wallstreetbets","cryptocurrency",
    "Bitcoin","Trading","FuturesTrading","scalping","technicalanalysis",
    "thetagang","swingtrading","Bogleheads","financialindependence",
    "forex_trading","CryptoMarkets","binance","ethtrader","SatoshiStreetBets",
]

TRADING_KEYWORDS = [
    "discord server trading","discord forex signals","discord crypto trading",
    "discord stock trading","discord options trading","discord futures trading",
    "discord day trading","join our discord trading","discord.gg trading signals",
    "trading discord invite","free trading discord","discord swing trading",
    "forex discord server","crypto signals discord","stock alerts discord",
    "discord trading community","scalping discord","algo trading discord",
    "pump discord server","discord.gg forex","discord.gg stocks",
]

DISBOARD_TAGS = [
    "trading","forex","crypto-trading","stocks","investing","day-trading",
    "options-trading","futures","cryptocurrency","signals","scalping",
    "swing-trading","algo-trading","stock-market","bitcoin","ethereum",
]

TOPGG_TAGS = [
    "trading","forex","crypto","stocks","investing","finance","signals",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

# ── Helpers ───────────────────────────────────────────────────────

def rand_ua():
    return random.choice(USER_AGENTS)

def extract_codes(text):
    codes = []
    for m in DISCORD_PATTERN.finditer(text or ""):
        code = m.group(1) or m.group(2)
        if code and 2 < len(code) < 50:
            codes.append(code)
    return codes

def build_invite_url(code):
    return f"https://discord.gg/{code}"

def log(msg, level="info"):
    with scrape_status["_lock"]:
        scrape_status["progress"].append({"msg": msg, "level": level, "ts": time.time()})
    getattr(logger, level)(msg)

def add_result(code, source, context=""):
    with scrape_status["_lock"]:
        if code in scrape_status["seen_codes"]:
            return False
        scrape_status["seen_codes"].add(code)
        scrape_status["results"].append({
            "code": code,
            "url": build_invite_url(code),
            "source": source,
            "context": context[:120],
            "found_at": datetime.datetime.now().strftime("%H:%M:%S"),
        })
    return True

def http_get(url, extra_headers=None, timeout=15, retries=3, delay=2):
    headers = {
        "User-Agent": rand_ua(),
        "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if extra_headers:
        headers.update(extra_headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 15 * (attempt + 1)
                log(f"  Rate limited on {url[:60]}… waiting {wait}s", "warning")
                time.sleep(wait)
            elif e.code in (403, 404, 410):
                return None
            else:
                time.sleep(delay)
        except Exception as e:
            if attempt == retries - 1:
                log(f"  Request failed [{url[:60]}]: {e}", "warning")
            time.sleep(delay)
    return None

def reddit_get(url):
    return http_get(url, extra_headers={"Accept": "application/json"}, retries=3, delay=3)

# ── Scrapers ──────────────────────────────────────────────────────

def scrape_reddit_subreddit(subreddit, limit=100):
    if not scrape_status["running"]: return 0
    found = 0
    for sort in ["new", "hot", "top"]:
        url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
        raw = reddit_get(url)
        if not raw: continue
        try:
            data = json.loads(raw)
        except Exception: continue
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            pd = post.get("data", {})
            text = " ".join([pd.get("title",""), pd.get("selftext",""), pd.get("url","")])
            for code in extract_codes(text):
                if add_result(code, f"Reddit r/{subreddit}", pd.get("title","")[:80]):
                    found += 1
        # Sample top-20 comment threads
        for post in posts[:20]:
            if not scrape_status["running"]: break
            pd = post.get("data", {})
            permalink = pd.get("permalink", "")
            if not permalink: continue
            curl = f"https://www.reddit.com{permalink}.json?limit=50"
            craw = reddit_get(curl)
            if not craw: continue
            try:
                cdata = json.loads(craw)
                for c in cdata[1]["data"]["children"]:
                    body = c.get("data", {}).get("body", "")
                    for code in extract_codes(body):
                        if add_result(code, f"Reddit r/{subreddit} comments", body[:80]):
                            found += 1
            except Exception: pass
            time.sleep(0.6)
        time.sleep(random.uniform(2, 3.5))
    return found


def scrape_reddit_search(keywords):
    if not scrape_status["running"]: return 0
    found = 0
    for kw in keywords:
        encoded = urllib.parse.quote(kw)
        url = f"https://www.reddit.com/search.json?q={encoded}&sort=new&limit=100&type=link,comment"
        raw = reddit_get(url)
        if not raw:
            time.sleep(2); continue
        try:
            data = json.loads(raw)
        except Exception: continue
        posts = data.get("data", {}).get("children", [])
        log(f"  Reddit search '{kw}': {len(posts)} posts")
        for post in posts:
            pd = post.get("data", {})
            text = " ".join([pd.get("title",""), pd.get("selftext",""), pd.get("body",""), pd.get("url","")])
            for code in extract_codes(text):
                if add_result(code, f"Reddit search: {kw}", pd.get("title", pd.get("body",""))[:80]):
                    found += 1
        time.sleep(random.uniform(2, 4))
    return found


def scrape_disboard(pages=3):
    if not scrape_status["running"]: return 0
    found = 0
    for tag in DISBOARD_TAGS:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://disboard.org/servers/tag/{tag}?page={page}&sort=-member_count"
            html = http_get(url, extra_headers={"Referer": "https://disboard.org/"})
            if html:
                inv = re.compile(
                    r'href=["\']https?://discord(?:app)?\.com/invite/([A-Za-z0-9\-_]+)["\']'
                    r'|href=["\']https?://discord\.gg/([A-Za-z0-9\-_]+)["\']', re.I)
                for m in inv.finditer(html):
                    code = m.group(1) or m.group(2)
                    if code and add_result(code, f"Disboard tag:{tag}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(1.5, 3))
    return found


def scrape_discord_me(pages=5):
    if not scrape_status["running"]: return 0
    found = 0
    tags = ["trading","crypto","forex","stocks","investing","signals","finance"]
    for tag in tags:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://discord.me/servers/{page}?keyword={tag}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"Discord.me tag:{tag}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(1.5, 3))
    return found


def scrape_discords_com(pages=3):
    """discords.com server listing"""
    if not scrape_status["running"]: return 0
    found = 0
    tags = ["trading","forex","crypto","stocks","investing","finance","signals"]
    for tag in tags:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://discords.com/servers/{tag}?page={page}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"Discords.com tag:{tag}", f"page {page}"):
                        found += 1
                # also look for data- attributes with invite codes
                inv = re.compile(r'data-invite=["\']([A-Za-z0-9\-_]{2,50})["\']', re.I)
                for m in inv.finditer(html):
                    if add_result(m.group(1), f"Discords.com tag:{tag}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(1.5, 3))
    return found


def scrape_discord_boats(pages=3):
    """discord.boats listing"""
    if not scrape_status["running"]: return 0
    found = 0
    tags = ["trading","crypto","forex","stocks","investing"]
    for tag in tags:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://discord.boats/tag/{tag}?page={page}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"Discord.boats tag:{tag}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(1.5, 2.5))
    return found


def scrape_top_gg(pages=3):
    """top.gg server listings"""
    if not scrape_status["running"]: return 0
    found = 0
    for tag in TOPGG_TAGS:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://top.gg/servers/tag/{tag}?page={page}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"Top.gg tag:{tag}", f"page {page}"):
                        found += 1
                # top.gg sometimes puts invite in data-invite
                inv = re.compile(r'(?:invite|server)/([A-Za-z0-9\-_]{2,50})["\s]', re.I)
                for m in inv.finditer(html):
                    code = m.group(1)
                    if len(code) > 3:
                        if add_result(code, f"Top.gg tag:{tag}", f"page {page}"):
                            found += 1
            time.sleep(random.uniform(2, 3.5))
    return found


def scrape_discordservers_com(pages=3):
    """discordservers.com listing"""
    if not scrape_status["running"]: return 0
    found = 0
    tags = ["trading","forex","crypto","stocks","investing","finance"]
    for tag in tags:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://discordservers.com/browse/{tag}/1/{page}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"DiscordServers.com tag:{tag}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(1.5, 3))
    return found


def scrape_find_discord(pages=3):
    """find-discord.com listing"""
    if not scrape_status["running"]: return 0
    found = 0
    tags = ["trading","forex","crypto","stocks","finance","investing"]
    for tag in tags:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://find-discord.com/category/{tag}?page={page}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"Find-Discord.com tag:{tag}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(1.5, 2.5))
    return found


def scrape_discord_center(pages=3):
    """discord.center (European listing)"""
    if not scrape_status["running"]: return 0
    found = 0
    tags = ["trading","forex","crypto","stocks","investing"]
    for tag in tags:
        for page in range(1, pages + 1):
            if not scrape_status["running"]: return found
            url = f"https://discord.center/servers/{tag}?page={page}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"Discord.center tag:{tag}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(1.5, 2.5))
    return found


def scrape_nitter(keywords):
    """Nitter (Twitter mirror) — no login required."""
    if not scrape_status["running"]: return 0
    instances = [
        "nitter.poast.org",
        "nitter.privacydev.net",
        "nitter.cz",
        "nitter.1d4.us",
        "nitter.kavin.rocks",
    ]
    found = 0
    for kw in keywords:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(f"{kw} discord.gg")
        for inst in instances:
            url = f"https://{inst}/search?q={encoded}&f=tweets"
            html = http_get(url, timeout=12)
            if html:
                codes = extract_codes(html)
                for code in codes:
                    if add_result(code, f"Twitter/X via Nitter: {kw}", kw):
                        found += 1
                if codes:
                    log(f"  Nitter [{inst}] '{kw}': {len(codes)} links")
                break
            time.sleep(1)
        time.sleep(random.uniform(2, 4))
    return found


def scrape_github(keywords, pages=2):
    """
    GitHub code search for Discord invite links in public files.
    Uses unauthenticated search (limited but functional).
    """
    if not scrape_status["running"]: return 0
    found = 0
    search_terms = [
        "discord.gg trading forex",
        "discord.gg forex signals",
        "discord.gg stocks trading",
        "discord.gg crypto signals",
        "discord invite trading server",
        "discord.gg day trading",
    ]
    for term in search_terms:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(term)
        for page in range(1, pages + 1):
            url = f"https://github.com/search?q={encoded}&type=code&p={page}"
            html = http_get(url, extra_headers={"Accept": "text/html"})
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"GitHub search: {term[:40]}", f"page {page}"):
                        found += 1
            time.sleep(random.uniform(3, 5))  # GitHub is aggressive with rate limits
    return found


def scrape_pastebin(keywords):
    """
    Pastebin Google dork — search for trading Discord links on pastebin.
    Uses the public search endpoint (very limited without premium).
    """
    if not scrape_status["running"]: return 0
    found = 0
    # Pastebin public search (CSE-style)
    search_terms = [
        "site:pastebin.com discord.gg forex",
        "site:pastebin.com discord.gg trading",
        "site:pastebin.com discord.gg stocks",
        "site:pastebin.com discord.gg crypto signals",
    ]
    # We can also try fetching pastebin archive search
    for term in search_terms:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(term)
        # Try via Bing (more lenient than Google for scraping)
        url = f"https://www.bing.com/search?q={encoded}&count=20"
        html = http_get(url)
        if html:
            # Extract pastebin URLs from Bing results
            paste_urls = re.findall(r'href=["\']https?://pastebin\.com/([A-Za-z0-9]+)["\']', html)
            for paste_id in list(dict.fromkeys(paste_urls))[:10]:
                raw_url = f"https://pastebin.com/raw/{paste_id}"
                raw = http_get(raw_url)
                if raw:
                    for code in extract_codes(raw):
                        if add_result(code, f"Pastebin ({paste_id})", f"search: {term[:50]}"):
                            found += 1
                time.sleep(1)
        time.sleep(random.uniform(3, 5))
    return found


def scrape_bing(keywords):
    """
    Bing web search for Discord trading server links.
    Bing is more scraping-friendly than Google.
    """
    if not scrape_status["running"]: return 0
    found = 0
    search_terms = [
        "discord.gg forex trading server",
        "discord.gg stock trading server",
        "discord.gg crypto signals server",
        "\"discord.gg\" forex trading free",
        "\"discord.gg\" stocks signals free",
        "\"discord.gg\" day trading community",
        "\"discord.gg\" swing trading alerts",
        "\"discord.gg\" options trading signals",
        "\"discord.gg\" futures trading",
        "\"discord.gg\" crypto pump signals",
    ]
    for term in search_terms:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(term)
        url = f"https://www.bing.com/search?q={encoded}&count=50&first=1"
        html = http_get(url, extra_headers={"Accept-Language": "en-US,en;q=0.9"})
        if html:
            for code in extract_codes(html):
                if add_result(code, f"Bing: {term[:50]}", term):
                    found += 1
            # Also page 2
            url2 = f"https://www.bing.com/search?q={encoded}&count=50&first=51"
            html2 = http_get(url2)
            if html2:
                for code in extract_codes(html2):
                    if add_result(code, f"Bing p2: {term[:50]}", term):
                        found += 1
        time.sleep(random.uniform(3, 5))
    return found


def scrape_duckduckgo(keywords):
    """
    DuckDuckGo HTML search — very scraping-friendly.
    """
    if not scrape_status["running"]: return 0
    found = 0
    search_terms = [
        "discord.gg forex trading",
        "discord.gg stocks trading server",
        "discord.gg crypto signals",
        "discord.gg options trading",
        "discord.gg futures trading",
        "discord.gg swing trading",
        "discord.gg penny stocks",
        "discord.gg algorithmic trading",
        "discord.gg bitcoin signals",
        "discord.gg day trading",
    ]
    for term in search_terms:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(term)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        html = http_get(url, extra_headers={"Accept-Language": "en-US"})
        if html:
            for code in extract_codes(html):
                if add_result(code, f"DuckDuckGo: {term[:50]}", term):
                    found += 1
        time.sleep(random.uniform(3, 5))
    return found


def scrape_youtube_search(keywords):
    """
    YouTube search results page — many trading channels share Discord in descriptions/comments.
    """
    if not scrape_status["running"]: return 0
    found = 0
    search_terms = [
        "forex trading discord server free",
        "stock trading discord community",
        "crypto signals discord free",
        "day trading discord server",
        "options trading discord",
        "swing trading discord",
    ]
    for term in search_terms:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(term)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        html = http_get(url)
        if html:
            for code in extract_codes(html):
                if add_result(code, f"YouTube: {term[:50]}", term):
                    found += 1
        time.sleep(random.uniform(3, 5))
    return found


def scrape_telegram_preview(keywords):
    """
    Telegram web previews for trading groups that also share Discord links.
    """
    if not scrape_status["running"]: return 0
    found = 0
    # Try public Telegram search
    search_terms = [
        "forex discord",
        "trading signals discord",
        "crypto discord server",
        "stocks discord",
    ]
    for term in search_terms:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(term)
        url = f"https://www.bing.com/search?q=site:t.me+{encoded}+discord.gg"
        html = http_get(url)
        if html:
            # Extract t.me links
            tg_urls = re.findall(r'href=["\']https?://t\.me/([A-Za-z0-9_]+)["\']', html)
            for channel in list(dict.fromkeys(tg_urls))[:8]:
                tg_url = f"https://t.me/s/{channel}"
                page_html = http_get(tg_url)
                if page_html:
                    for code in extract_codes(page_html):
                        if add_result(code, f"Telegram @{channel}", f"from Bing: {term}"):
                            found += 1
                time.sleep(1.5)
        time.sleep(random.uniform(3, 4))
    return found


def scrape_steemit_hive(pages=2):
    """Steemit/Hive blockchain social — traders post Discord links here."""
    if not scrape_status["running"]: return 0
    found = 0
    tags = ["forex","trading","crypto","stocks","cryptocurrency","daytrading"]
    for tag in tags:
        for page in range(pages):
            if not scrape_status["running"]: return found
            url = f"https://hive.blog/trending/{tag}"
            html = http_get(url)
            if html:
                for code in extract_codes(html):
                    if add_result(code, f"Hive.blog tag:{tag}", f"page {page+1}"):
                        found += 1
            time.sleep(random.uniform(2, 3))
    return found


def scrape_tradingview(pages=2):
    """TradingView public streams and ideas — traders embed Discord links."""
    if not scrape_status["running"]: return 0
    found = 0
    terms = ["forex","stocks","crypto","signals","daytrading"]
    for term in terms:
        if not scrape_status["running"]: break
        url = f"https://www.tradingview.com/scripts/?script_type=study&search={term}"
        html = http_get(url)
        if html:
            for code in extract_codes(html):
                if add_result(code, f"TradingView: {term}", ""):
                    found += 1
        time.sleep(random.uniform(2, 3))
    return found


def scrape_4chan_biz():
    """4chan /biz/ board — heavy Discord trading link activity."""
    if not scrape_status["running"]: return 0
    found = 0
    try:
        # Get catalog JSON
        url = "https://a.4cdn.org/biz/catalog.json"
        raw = http_get(url, extra_headers={"Accept": "application/json"})
        if not raw: return 0
        catalog = json.loads(raw)
        thread_ids = []
        for page in catalog:
            for thread in page.get("threads", []):
                com = thread.get("com", "") + thread.get("sub", "")
                if extract_codes(com):
                    for code in extract_codes(com):
                        if add_result(code, "4chan /biz/ catalog", com[:80]):
                            found += 1
                if any(k in com.lower() for k in ["discord","forex","trading","crypto","stocks","signals"]):
                    thread_ids.append(thread["no"])

        log(f"  4chan /biz/: {len(thread_ids)} relevant threads")
        for tid in thread_ids[:30]:
            if not scrape_status["running"]: break
            turl = f"https://a.4cdn.org/biz/thread/{tid}.json"
            raw = http_get(turl)
            if not raw: continue
            try:
                data = json.loads(raw)
                for post in data.get("posts", []):
                    text = post.get("com", "") + " " + post.get("sub", "")
                    for code in extract_codes(text):
                        if add_result(code, f"4chan /biz/ thread:{tid}", text[:80]):
                            found += 1
            except Exception: pass
            time.sleep(0.8)
    except Exception as e:
        log(f"  4chan error: {e}", "warning")
    return found


def scrape_stocktwits(keywords):
    """StockTwits public stream — traders share Discord links."""
    if not scrape_status["running"]: return 0
    found = 0
    symbols = ["FOREX","SPY","QQQ","TSLA","AAPL","BTC.X","ETH.X","GC_F","CL_F"]
    for sym in symbols:
        if not scrape_status["running"]: break
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json?limit=30"
        raw = http_get(url, extra_headers={"Accept": "application/json"})
        if raw:
            try:
                data = json.loads(raw)
                for msg in data.get("messages", []):
                    body = msg.get("body", "")
                    for code in extract_codes(body):
                        if add_result(code, f"StockTwits ${sym}", body[:80]):
                            found += 1
            except Exception: pass
        time.sleep(random.uniform(1.5, 2.5))
    return found


def scrape_medium(keywords):
    """Medium articles — trading writers often embed Discord invites."""
    if not scrape_status["running"]: return 0
    found = 0
    search_terms = [
        "discord trading server forex",
        "discord crypto signals free",
        "discord stock trading community",
        "discord day trading server",
    ]
    for term in search_terms:
        if not scrape_status["running"]: break
        encoded = urllib.parse.quote(f"site:medium.com {term} discord.gg")
        url = f"https://www.bing.com/search?q={encoded}&count=20"
        html = http_get(url)
        if html:
            medium_urls = re.findall(r'href=["\']https?://medium\.com/[^\s"\'<>]+["\']', html)
            for mu in list(dict.fromkeys(medium_urls))[:6]:
                mu = mu.strip('"\'')
                mhtml = http_get(mu)
                if mhtml:
                    for code in extract_codes(mhtml):
                        if add_result(code, f"Medium: {term[:40]}", mu[:80]):
                            found += 1
                time.sleep(1.5)
        time.sleep(random.uniform(3, 4))
    return found


# ── Main orchestrator ─────────────────────────────────────────────

def run_scrape(config):
    scrape_status["running"] = True
    scrape_status["results"] = []
    scrape_status["seen_codes"] = set()
    scrape_status["progress"] = []
    scrape_status["error"] = None

    try:
        sources = config.get("sources", [])
        custom_kws = config.get("keywords", [])
        custom_subs = config.get("subreddits", [])
        depth = config.get("depth", "normal")

        subreddits = custom_subs if custom_subs else TRADING_SUBREDDITS
        keywords   = custom_kws  if custom_kws  else TRADING_KEYWORDS

        pages     = {"quick": 1, "normal": 3, "deep": 7}.get(depth, 3)
        sub_limit = {"quick": 50, "normal": 100, "deep": 200}.get(depth, 100)
        tw_kws    = keywords[:3] if depth == "quick" else keywords[:8]

        # ── Reddit ─────────────────────────────────────────────────
        if "reddit" in sources:
            log("🔍 Scraping Reddit subreddits…")
            subs = subreddits[:5] if depth == "quick" else subreddits
            for i, sub in enumerate(subs):
                if not scrape_status["running"]: break
                log(f"  [{i+1}/{len(subs)}] r/{sub}")
                n = scrape_reddit_subreddit(sub, limit=sub_limit)
                log(f"  → {n} new from r/{sub}")
                time.sleep(random.uniform(2, 4))
            log("🔍 Reddit keyword search…")
            kws = keywords[:3] if depth == "quick" else keywords
            n = scrape_reddit_search(kws)
            log(f"  → {n} new from Reddit search")

        # ── Disboard ───────────────────────────────────────────────
        if "disboard" in sources:
            log("🔍 Scraping Disboard.org…")
            n = scrape_disboard(pages=pages)
            log(f"  → {n} from Disboard")

        # ── Discord.me ─────────────────────────────────────────────
        if "discordme" in sources:
            log("🔍 Scraping Discord.me…")
            n = scrape_discord_me(pages=pages)
            log(f"  → {n} from Discord.me")

        # ── Discords.com ───────────────────────────────────────────
        if "discords_com" in sources:
            log("🔍 Scraping Discords.com…")
            n = scrape_discords_com(pages=pages)
            log(f"  → {n} from Discords.com")

        # ── Discord.boats ──────────────────────────────────────────
        if "discord_boats" in sources:
            log("🔍 Scraping Discord.boats…")
            n = scrape_discord_boats(pages=pages)
            log(f"  → {n} from Discord.boats")

        # ── Top.gg ────────────────────────────────────────────────
        if "topgg" in sources:
            log("🔍 Scraping Top.gg…")
            n = scrape_top_gg(pages=pages)
            log(f"  → {n} from Top.gg")

        # ── DiscordServers.com ─────────────────────────────────────
        if "discordservers" in sources:
            log("🔍 Scraping DiscordServers.com…")
            n = scrape_discordservers_com(pages=pages)
            log(f"  → {n} from DiscordServers.com")

        # ── Find-Discord.com ───────────────────────────────────────
        if "find_discord" in sources:
            log("🔍 Scraping Find-Discord.com…")
            n = scrape_find_discord(pages=pages)
            log(f"  → {n} from Find-Discord.com")

        # ── Discord.center ─────────────────────────────────────────
        if "discord_center" in sources:
            log("🔍 Scraping Discord.center…")
            n = scrape_discord_center(pages=pages)
            log(f"  → {n} from Discord.center")

        # ── Twitter / Nitter ───────────────────────────────────────
        if "twitter" in sources:
            log("🔍 Scraping Twitter/X via Nitter…")
            n = scrape_nitter(tw_kws)
            log(f"  → {n} from Twitter/X")

        # ── 4chan /biz/ ────────────────────────────────────────────
        if "fourchan" in sources:
            log("🔍 Scraping 4chan /biz/…")
            n = scrape_4chan_biz()
            log(f"  → {n} from 4chan /biz/")

        # ── StockTwits ─────────────────────────────────────────────
        if "stocktwits" in sources:
            log("🔍 Scraping StockTwits…")
            n = scrape_stocktwits(keywords)
            log(f"  → {n} from StockTwits")

        # ── DuckDuckGo ─────────────────────────────────────────────
        if "duckduckgo" in sources:
            log("🔍 Searching DuckDuckGo…")
            n = scrape_duckduckgo(keywords)
            log(f"  → {n} from DuckDuckGo")

        # ── Bing ───────────────────────────────────────────────────
        if "bing" in sources:
            log("🔍 Searching Bing…")
            n = scrape_bing(keywords)
            log(f"  → {n} from Bing")

        # ── YouTube ────────────────────────────────────────────────
        if "youtube" in sources:
            log("🔍 Searching YouTube…")
            n = scrape_youtube_search(keywords)
            log(f"  → {n} from YouTube")

        # ── Telegram ───────────────────────────────────────────────
        if "telegram" in sources:
            log("🔍 Probing Telegram channels…")
            n = scrape_telegram_preview(keywords)
            log(f"  → {n} from Telegram")

        # ── GitHub ─────────────────────────────────────────────────
        if "github" in sources:
            log("🔍 Searching GitHub code…")
            n = scrape_github(keywords, pages=2)
            log(f"  → {n} from GitHub")

        # ── Pastebin ───────────────────────────────────────────────
        if "pastebin" in sources:
            log("🔍 Scanning Pastebin…")
            n = scrape_pastebin(keywords)
            log(f"  → {n} from Pastebin")

        # ── Hive.blog ─────────────────────────────────────────────
        if "hive" in sources:
            log("🔍 Scraping Hive.blog…")
            n = scrape_steemit_hive(pages=pages)
            log(f"  → {n} from Hive.blog")

        # ── TradingView ────────────────────────────────────────────
        if "tradingview" in sources:
            log("🔍 Scraping TradingView…")
            n = scrape_tradingview(pages=pages)
            log(f"  → {n} from TradingView")

        # ── Medium ─────────────────────────────────────────────────
        if "medium" in sources:
            log("🔍 Scanning Medium articles…")
            n = scrape_medium(keywords)
            log(f"  → {n} from Medium")

        total = len(scrape_status["results"])
        log(f"✅ Done! Found {total} unique Discord server links.", "info")
        save_results()

    except Exception as e:
        scrape_status["error"] = str(e)
        log(f"❌ Fatal error: {e}", "error")
        logger.exception("Scrape error")
    finally:
        scrape_status["running"] = False


def save_results():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join("results", f"discord_links_{ts}.json")
    os.makedirs("results", exist_ok=True)
    with open(path, "w") as f:
        json.dump(scrape_status["results"], f, indent=2)
    log(f"💾 Saved to {path}")
    return path


# ── Flask Routes ──────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/start", methods=["POST"])
def start_scrape():
    if scrape_status["running"]:
        return jsonify({"error": "Already running"}), 400
    config = request.get_json(silent=True) or {}
    t = threading.Thread(target=run_scrape, args=(config,), daemon=True)
    t.start()
    return jsonify({"status": "started"})

@app.route("/api/stop", methods=["POST"])
def stop_scrape():
    scrape_status["running"] = False
    return jsonify({"status": "stopped"})

@app.route("/api/status")
def get_status():
    return jsonify({
        "running": scrape_status["running"],
        "count": len(scrape_status["results"]),
        "progress": scrape_status["progress"][-80:],
        "error": scrape_status["error"],
    })

@app.route("/api/results")
def get_results():
    return jsonify(scrape_status["results"])

@app.route("/api/export")
def export_results():
    fmt = request.args.get("fmt", "json")
    results = scrape_status["results"]
    if fmt == "csv":
        lines = ["code,url,source,context,found_at"]
        for r in results:
            ctx = r["context"].replace('"', '""')
            src = r["source"].replace('"', '""')
            lines.append(f'"{r["code"]}","{r["url"]}","{src}","{ctx}","{r["found_at"]}"')
        return Response("\n".join(lines), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment;filename=discord_links.csv"})
    return Response(json.dumps(results, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment;filename=discord_links.json"})

@app.route("/api/clear", methods=["POST"])
def clear_results():
    scrape_status["results"] = []
    scrape_status["seen_codes"] = set()
    scrape_status["progress"] = []
    return jsonify({"status": "cleared"})

if __name__ == "__main__":
    os.makedirs("results", exist_ok=True)
    print("\n🎯 Discord Link Hunter v2 started!")
    print("👉  Open http://127.0.0.1:5000 in your browser\n")
    app.run(debug=False, port=5000, threaded=True)
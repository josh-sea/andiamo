"""
Builds the static docs/ site from brain/ markdown files.
Geocities-inspired HTML with page routing (no hash routing).
"""

import os
import re
import json
from datetime import datetime
from bot.config import BRAIN_DIR, DOCS_DIR, THESES_DIR, CONNECTIONS_DIR, VALIDATIONS_DIR
import bot.brain as brain_mod

# GitHub Pages serves from /andiamo/ — all absolute site links must include this prefix
SITE_BASE = "/andiamo"


def _url(path: str) -> str:
    """Prefix a site-root-relative path with the GitHub Pages base."""
    return f"{SITE_BASE}{path}"


def _ensure_docs():
    for d in [DOCS_DIR, os.path.join(DOCS_DIR, "theses"), os.path.join(DOCS_DIR, "connections"),
              os.path.join(DOCS_DIR, "validations"), os.path.join(DOCS_DIR, "assets")]:
        os.makedirs(d, exist_ok=True)
    # Prevent GitHub Pages from running Jekyll on our pre-built HTML
    nojekyll = os.path.join(DOCS_DIR, ".nojekyll")
    if not os.path.exists(nojekyll):
        open(nojekyll, "w").close()


def _md_to_html(text: str) -> str:
    """Minimal markdown → HTML conversion."""
    text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"^- (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
    text = re.sub(r"\[\[(.+?)\]\]", lambda m: f'<a href="{_url(f"/theses/{m.group(1)}.html")}">[[{m.group(1)}]]</a>', text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"^---$", r"<hr>", text, flags=re.MULTILINE)
    paragraphs = []
    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if block and not block.startswith("<"):
            block = f"<p>{block}</p>"
        paragraphs.append(block)
    return "\n".join(paragraphs)


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.index("---", 3)
        return text[end + 3:].strip()
    return text


def _page(title: str, body: str, breadcrumb: str = "", active_nav: str = "") -> str:
    nav_items = [
        ("Home", _url("/index.html"), "home"),
        ("Theses", _url("/theses/index.html"), "theses"),
        ("Connections", _url("/connections/index.html"), "connections"),
        ("Validations", _url("/validations/index.html"), "validations"),
        ("Portfolio", _url("/portfolio.html"), "portfolio"),
    ]
    nav_html = ""
    for label, href, key in nav_items:
        active = ' class="active"' if key == active_nav else ""
        nav_html += f'<li{active}><a href="{href}">{label}</a></li>\n'

    bc = f'<div class="breadcrumb">{breadcrumb}</div>' if breadcrumb else ""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — ANDIAMO</title>
<link rel="stylesheet" href="{_url('/assets/style.css')}">
</head>
<body>
<div id="container">
  <header>
    <div id="banner">
      <span class="blink">&#9733;</span>
      ANDIAMO FINANCIAL RESEARCH BOT
      <span class="blink">&#9733;</span>
      <div id="ticker-sub">autonomous market intelligence since {datetime.utcnow().year}</div>
    </div>
    <nav>
      <ul>{nav_html}</ul>
    </nav>
    {bc}
  </header>
  <main>
    <div class="page-title"><h1>{title}</h1></div>
    {body}
  </main>
  <footer>
    <p>&#9670; ANDIAMO v1.0 &#9670; Paper Trading Only &#9670; Not Financial Advice &#9670;</p>
    <p><small>Last updated: {now}</small></p>
  </footer>
</div>
</body>
</html>"""


def _verdict_badge(verdict: str) -> str:
    classes = {
        "bullish": "badge-bull",
        "bearish": "badge-bear",
        "validated": "badge-bull",
        "invalidated": "badge-bear",
        "mixed": "badge-mixed",
        "neutral": "badge-neutral",
        "open": "badge-open",
    }
    cls = classes.get(verdict.lower(), "badge-open")
    return f'<span class="badge {cls}">{verdict.upper()}</span>'


def build_index(theses: list[dict]):
    open_t = [t for t in theses if t["status"] == "open"]
    validated = [t for t in theses if t["status"] == "validated"]
    invalidated = [t for t in theses if t["status"] == "invalidated"]

    def thesis_row(t):
        badge = _verdict_badge(t.get("verdict") or t["status"])
        tags = " ".join(f'<span class="tag">{tag}</span>' for tag in t.get("tags", []))
        slug = t["slug"]
        href = _url(f"/theses/{slug}.html")
        return (
            f'<tr><td><a href="{href}">{t["title"]}</a></td>'
            f'<td>{badge}</td><td>{tags}</td><td>{t["created"]}</td></tr>'
        )

    def section(title, items):
        if not items:
            return ""
        rows = "\n".join(thesis_row(t) for t in items)
        return f"""
<section>
  <h2>&#9671; {title}</h2>
  <table class="thesis-table">
    <thead><tr><th>Thesis</th><th>Status</th><th>Tags</th><th>Date</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""

    body = f"""
<div class="marquee-wrap"><marquee>&#9830; LIVE RESEARCH &#9830; AUTONOMOUS ANALYSIS &#9830; PATTERN RECOGNITION &#9830; KNOWLEDGE GRAPH UPDATED DAILY &#9830;</marquee></div>

<div class="stats-bar">
  <span class="stat">&#128202; {len(theses)} THESES</span>
  <span class="stat">&#9989; {len(validated)} VALIDATED</span>
  <span class="stat">&#10060; {len(invalidated)} INVALIDATED</span>
  <span class="stat">&#128269; {len(open_t)} OPEN</span>
</div>

{section("Active Investigations", open_t)}
{section("Validated", validated)}
{section("Invalidated", invalidated)}

<section>
  <h2>&#9671; About</h2>
  <div class="about-box">
    <p>ANDIAMO is an autonomous financial research agent. It reads news, scans Reddit, pulls price history,
    and builds a linked knowledge graph of market theses. It does lookback analysis to test hypotheses
    against historical data and validates predictions over time.</p>
    <p><strong>NOT FINANCIAL ADVICE.</strong> All trading is paper-only.</p>
  </div>
</section>
"""
    path = os.path.join(DOCS_DIR, "index.html")
    with open(path, "w") as f:
        f.write(_page("Home", body, active_nav="home"))


def build_thesis_page(thesis: dict, content: str):
    s = thesis
    body_md = _strip_frontmatter(content)
    body_html = _md_to_html(body_md)
    verdict = s.get("verdict") or s.get("status", "open")
    badge = _verdict_badge(verdict)
    tags = " ".join(f'<span class="tag">{t}</span>' for t in s.get("tags", []))
    body = f"""
<div class="thesis-meta">
  {badge}
  <span class="meta-date">&#128197; {s.get('created', '')}</span>
  {tags}
</div>
<div class="thesis-body">{body_html}</div>
"""
    path = os.path.join(DOCS_DIR, "theses", f"{s['slug']}.html")
    with open(path, "w") as f:
        f.write(_page(s["title"], body, breadcrumb=f'<a href="{_url("/index.html")}">Home</a> &rsaquo; <a href="{_url("/theses/index.html")}">Theses</a>', active_nav="theses"))


def build_theses_index(theses: list[dict]):
    rows = ""
    for t in theses:
        badge = _verdict_badge(t.get("verdict") or t["status"])
        tags = " ".join(f'<span class="tag">{tag}</span>' for tag in t.get("tags", []))
        slug = t["slug"]
        href = _url(f"/theses/{slug}.html")
        rows += (
            f'<tr><td><a href="{href}">{t["title"]}</a></td>'
            f'<td>{badge}</td><td>{tags}</td><td>{t["created"]}</td></tr>\n'
        )
    body = f"""
<table class="thesis-table">
  <thead><tr><th>Title</th><th>Status</th><th>Tags</th><th>Created</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    path = os.path.join(DOCS_DIR, "theses", "index.html")
    with open(path, "w") as f:
        f.write(_page("All Theses", body, breadcrumb=f'<a href="{_url("/index.html")}">Home</a>', active_nav="theses"))


def build_connections_index():
    items = []
    for fname in sorted(os.listdir(CONNECTIONS_DIR)):
        if fname.endswith(".md"):
            items.append(fname[:-3])
    rows = "\n".join(f'<li><a href="{_url(f"/connections/{s}.html")}">{s.replace("-", " ").title()}</a></li>' for s in items)
    body = f"<ul class='link-list'>{rows}</ul>" if rows else "<p>No connections yet.</p>"
    path = os.path.join(DOCS_DIR, "connections", "index.html")
    with open(path, "w") as f:
        f.write(_page("Connections", body, active_nav="connections"))


def build_validations_index():
    items = []
    for fname in sorted(os.listdir(VALIDATIONS_DIR)):
        if fname.endswith(".md"):
            items.append(fname[:-3])
    rows = "\n".join(f'<li><a href="{_url(f"/validations/{s}.html")}">{s.replace("-", " ").title()}</a></li>' for s in items)
    body = f"<ul class='link-list'>{rows}</ul>" if rows else "<p>No validations run yet.</p>"
    path = os.path.join(DOCS_DIR, "validations", "index.html")
    with open(path, "w") as f:
        f.write(_page("Validations", body, active_nav="validations"))


def build_portfolio_page():
    try:
        from bot.sources import alpaca
        acct = alpaca.get_account()
        positions = alpaca.get_positions()
        pos_rows = ""
        for p in positions:
            pl_cls = "positive" if p["unrealized_pl"] >= 0 else "negative"
            pos_rows += (
                f'<tr><td>{p["symbol"]}</td><td>{p["qty"]:.2f}</td>'
                f'<td>${p["avg_entry_price"]:.2f}</td>'
                f'<td>${p["market_value"]:.2f}</td>'
                f'<td class="{pl_cls}">${p["unrealized_pl"]:.2f} ({float(p["unrealized_plpc"])*100:.1f}%)</td></tr>\n'
            )
        body = f"""
<div class="stats-bar">
  <span class="stat">EQUITY: ${acct['equity']:,.2f}</span>
  <span class="stat">CASH: ${acct['cash']:,.2f}</span>
  <span class="stat">BUYING POWER: ${acct['buying_power']:,.2f}</span>
</div>
<h2>&#9671; Open Positions</h2>
<table class="thesis-table">
  <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Mkt Value</th><th>Unrealized P&L</th></tr></thead>
  <tbody>{pos_rows if pos_rows else '<tr><td colspan="5">No open positions</td></tr>'}</tbody>
</table>
<p class="disclaimer">&#9888; Paper trading account only. Not real money.</p>"""
    except Exception as e:
        body = f'<div class="error-box">Could not load portfolio: {e}</div>'

    path = os.path.join(DOCS_DIR, "portfolio.html")
    with open(path, "w") as f:
        f.write(_page("Portfolio", body, active_nav="portfolio"))


def build_css():
    css = """
/* ANDIAMO — Geocities-inspired finance bot */

:root {
  --bg: #000022;
  --bg2: #000044;
  --bg3: #000033;
  --border: #0055ff;
  --border2: #00aaff;
  --text: #ccddff;
  --text-bright: #ffffff;
  --accent: #ffcc00;
  --accent2: #ff6600;
  --bull: #00ff88;
  --bear: #ff3333;
  --link: #66aaff;
  --link-hover: #ffcc00;
  --font-mono: "Courier New", monospace;
  --font-main: "Verdana", "Arial", sans-serif;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  background-image:
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0, 85, 255, 0.03) 2px,
      rgba(0, 85, 255, 0.03) 4px
    );
  color: var(--text);
  font-family: var(--font-main);
  font-size: 14px;
  line-height: 1.6;
}

#container {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 16px;
}

/* HEADER */
header {
  border-bottom: 3px solid var(--border);
  padding-bottom: 8px;
  margin-bottom: 24px;
}

#banner {
  background: linear-gradient(135deg, #000066 0%, #000022 50%, #000066 100%);
  border: 2px solid var(--accent);
  border-bottom: none;
  text-align: center;
  padding: 16px 8px;
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: bold;
  color: var(--accent);
  text-shadow: 0 0 8px var(--accent), 0 0 20px rgba(255,204,0,0.4);
  letter-spacing: 3px;
  text-transform: uppercase;
  margin-top: 16px;
}

#ticker-sub {
  font-size: 11px;
  color: var(--border2);
  letter-spacing: 2px;
  margin-top: 4px;
  text-transform: lowercase;
}

.blink {
  animation: blink 1s step-end infinite;
  color: var(--accent2);
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* NAV */
nav { background: var(--bg2); border: 1px solid var(--border); margin-top: 0; }
nav ul { list-style: none; display: flex; flex-wrap: wrap; }
nav li a {
  display: block;
  padding: 8px 16px;
  color: var(--link);
  text-decoration: none;
  font-family: var(--font-mono);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
  border-right: 1px solid var(--border);
  transition: background 0.15s;
}
nav li a:hover, nav li.active a {
  background: var(--border);
  color: var(--text-bright);
}

/* BREADCRUMB */
.breadcrumb {
  font-size: 11px;
  padding: 4px 8px;
  color: #556688;
  border-bottom: 1px solid #001144;
}
.breadcrumb a { color: var(--link); text-decoration: none; }

/* MARQUEE */
.marquee-wrap {
  background: var(--bg3);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
  padding: 4px 0;
  margin-bottom: 16px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
}

/* STATS BAR */
.stats-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.stat {
  background: var(--bg2);
  border: 1px solid var(--border);
  padding: 6px 14px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--border2);
  text-transform: uppercase;
}

/* PAGE TITLE */
.page-title { margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
.page-title h1 {
  font-family: var(--font-mono);
  font-size: 20px;
  color: var(--text-bright);
  text-transform: uppercase;
  letter-spacing: 2px;
}

/* SECTIONS */
section { margin-bottom: 32px; }
section h2 {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 2px;
  margin-bottom: 12px;
  padding-bottom: 4px;
  border-bottom: 1px dashed var(--border);
}
section h3 {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--border2);
  margin: 12px 0 6px;
}

/* TABLES */
.thesis-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.thesis-table th {
  background: var(--bg2);
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--border2);
  text-transform: uppercase;
  letter-spacing: 1px;
}
.thesis-table td {
  border: 1px solid #001144;
  padding: 6px 10px;
  vertical-align: top;
}
.thesis-table tr:nth-child(even) td { background: rgba(0,0,68,0.4); }
.thesis-table tr:hover td { background: rgba(0,85,255,0.1); }
.thesis-table a { color: var(--link); text-decoration: none; }
.thesis-table a:hover { color: var(--link-hover); text-decoration: underline; }

/* BADGES */
.badge {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: bold;
  padding: 2px 8px;
  border-radius: 2px;
  letter-spacing: 1px;
}
.badge-bull { background: rgba(0,255,136,0.15); color: var(--bull); border: 1px solid var(--bull); }
.badge-bear { background: rgba(255,51,51,0.15); color: var(--bear); border: 1px solid var(--bear); }
.badge-open { background: rgba(0,170,255,0.15); color: var(--border2); border: 1px solid var(--border2); }
.badge-mixed { background: rgba(255,102,0,0.15); color: var(--accent2); border: 1px solid var(--accent2); }
.badge-neutral { background: rgba(100,100,150,0.2); color: #8899cc; border: 1px solid #334466; }

/* TAGS */
.tag {
  display: inline-block;
  font-size: 10px;
  background: rgba(0,85,255,0.15);
  border: 1px solid #002266;
  color: var(--border2);
  padding: 1px 6px;
  margin: 1px;
  border-radius: 2px;
  font-family: var(--font-mono);
}

/* THESIS CONTENT */
.thesis-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding: 8px;
  background: var(--bg2);
  border: 1px solid var(--border);
}
.meta-date { font-size: 11px; color: #556688; font-family: var(--font-mono); }

.thesis-body {
  background: rgba(0,0,44,0.5);
  border: 1px solid #001144;
  border-left: 3px solid var(--border);
  padding: 20px;
  line-height: 1.8;
}
.thesis-body h1, .thesis-body h2, .thesis-body h3 {
  font-family: var(--font-mono);
  color: var(--text-bright);
  margin: 20px 0 10px;
}
.thesis-body h1 { font-size: 18px; color: var(--accent); border-bottom: 1px dashed var(--border); padding-bottom: 4px; }
.thesis-body h2 { font-size: 14px; color: var(--border2); }
.thesis-body h3 { font-size: 13px; color: var(--text); }
.thesis-body p { margin-bottom: 12px; }
.thesis-body li { margin: 4px 0 4px 20px; }
.thesis-body code {
  background: rgba(0,85,255,0.1);
  border: 1px solid #001166;
  padding: 1px 5px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
}
.thesis-body a { color: var(--link); }
.thesis-body a:hover { color: var(--link-hover); }
.thesis-body hr { border: none; border-top: 1px dashed #001144; margin: 20px 0; }
.thesis-body strong { color: var(--text-bright); }

/* MISC */
.about-box {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent2);
  padding: 16px;
}
.about-box p { margin-bottom: 8px; }

.link-list { list-style: none; }
.link-list li { margin: 6px 0; }
.link-list a { color: var(--link); text-decoration: none; font-family: var(--font-mono); font-size: 13px; }
.link-list a:hover { color: var(--link-hover); }

.error-box {
  background: rgba(255,51,51,0.1);
  border: 1px solid var(--bear);
  padding: 12px;
  font-family: var(--font-mono);
  color: var(--bear);
}

.disclaimer {
  font-size: 11px;
  color: #556688;
  margin-top: 12px;
  font-style: italic;
}

.positive { color: var(--bull); }
.negative { color: var(--bear); }

/* FOOTER */
footer {
  border-top: 2px solid var(--border);
  margin-top: 40px;
  padding: 16px 0;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 11px;
  color: #334466;
}
footer small { color: #223355; }

/* RESPONSIVE */
@media (max-width: 600px) {
  #banner { font-size: 14px; letter-spacing: 1px; }
  nav li a { padding: 6px 10px; font-size: 11px; }
  .stats-bar { gap: 4px; }
}
"""
    path = os.path.join(DOCS_DIR, "assets", "style.css")
    with open(path, "w") as f:
        f.write(css)


def build():
    _ensure_docs()
    build_css()

    theses = brain_mod.list_theses()

    # Individual thesis pages
    for t in theses:
        content = brain_mod.get_thesis(t["slug"])
        if content:
            build_thesis_page(t, content)

    # Connections
    for fname in os.listdir(CONNECTIONS_DIR):
        if fname.endswith(".md"):
            src = os.path.join(CONNECTIONS_DIR, fname)
            dst = os.path.join(DOCS_DIR, "connections", fname.replace(".md", ".html"))
            with open(src) as f:
                raw = f.read()
            body = f'<div class="thesis-body">{_md_to_html(_strip_frontmatter(raw))}</div>'
            title = fname[:-3].replace("-", " ").title()
            with open(dst, "w") as f:
                f.write(_page(title, body, active_nav="connections"))

    # Validations
    for fname in os.listdir(VALIDATIONS_DIR):
        if fname.endswith(".md"):
            src = os.path.join(VALIDATIONS_DIR, fname)
            dst = os.path.join(DOCS_DIR, "validations", fname.replace(".md", ".html"))
            with open(src) as f:
                raw = f.read()
            body = f'<div class="thesis-body">{_md_to_html(_strip_frontmatter(raw))}</div>'
            title = fname[:-3].replace("-", " ").title()
            with open(dst, "w") as f:
                f.write(_page(title, body, active_nav="validations"))

    build_theses_index(theses)
    build_connections_index()
    build_validations_index()
    build_portfolio_page()
    build_index(theses)

"""
Builds the static docs/ site from brain/ markdown files.
Geocities-inspired HTML with page routing (no hash routing).
"""

import os
import re
import json
import html
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
              os.path.join(DOCS_DIR, "validations"), os.path.join(DOCS_DIR, "assets"),
              os.path.join(DOCS_DIR, "scans"), os.path.join(DOCS_DIR, "journal"),
              os.path.join(DOCS_DIR, "lab", "notebook"), os.path.join(DOCS_DIR, "lab", "figures")]:
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
        if block and not re.match(r"<(h[1-6]|li|hr|ul|ol|div|table|pre|details)\b", block):
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
        ("Scans", _url("/scans/index.html"), "scans"),
        ("Theses", _url("/theses/index.html"), "theses"),
        ("Connections", _url("/connections/index.html"), "connections"),
        ("Validations", _url("/validations/index.html"), "validations"),
        ("Portfolio", _url("/portfolio.html"), "portfolio"),
        ("Lab", _url("/lab/index.html"), "lab"),
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


_SCAN_META_KEYS = {
    "scan_date", "date", "scan_type", "report_type", "analyst", "scanner", "generated_by",
    "generated", "generated_at", "scan_id", "id", "status",
}
_LEAD_TITLE_KEYS = ("title", "headline", "one_liner", "name")
_LEAD_HEADER_KEYS = {"rank", "id", "signal_strength", "signal_strength_label", "category", "type", "signal_type"}


def _find_scan_payload(data):
    """Scans have no fixed schema; locate the dict that holds the leads list."""
    if isinstance(data, dict):
        if isinstance(data.get("leads"), list):
            return data
        for v in data.values():
            found = _find_scan_payload(v)
            if found is not None:
                return found
    return None


def _label(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _render_value(value) -> str:
    if isinstance(value, dict):
        items = "".join(
            f"<li><strong>{html.escape(_label(k))}:</strong> {_render_value(v)}</li>"
            for k, v in value.items() if v not in (None, "", [], {})
        )
        return f"<ul>{items}</ul>"
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_render_value(v)}</li>" for v in value) + "</ul>"
    return html.escape(str(value))


def _render_fields(obj: dict, skip: set) -> str:
    out = ""
    for k, v in obj.items():
        if k in skip or v in (None, "", [], {}):
            continue
        if isinstance(v, (list, dict)):
            out += f"<div class='scan-field'><strong>{html.escape(_label(k))}:</strong>{_render_value(v)}</div>"
        else:
            out += f"<p><strong>{html.escape(_label(k))}:</strong> {_render_value(v)}</p>"
    return out


def _lead_title(lead: dict) -> str:
    return next((str(lead[k]) for k in _LEAD_TITLE_KEYS if lead.get(k)), "Untitled lead")


def _list_scans() -> list[dict]:
    from bot.config import ASSETS_DIR
    scans = []
    if not os.path.exists(ASSETS_DIR):
        return scans
    for fname in sorted(os.listdir(ASSETS_DIR), reverse=True):
        if not (fname.startswith("scan-") and fname.endswith(".md")):
            continue
        path = os.path.join(ASSETS_DIR, fname)
        with open(path) as f:
            raw = f.read()
        payload = {}
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            try:
                payload = _find_scan_payload(json.loads(json_match.group(1))) or {}
            except json.JSONDecodeError:
                pass
        leads = [l for l in payload.get("leads", []) if isinstance(l, dict)]
        headline = next(
            (payload[k] for k in ("headline_context", "summary", "scan_summary", "macro_context",
                                  "market_context", "macro_backdrop_summary")
             if isinstance(payload.get(k), str) and payload.get(k)),
            "",
        )
        if not headline and leads:
            headline = _lead_title(leads[0])
        scans.append({
            "date": fname[5:-3],
            "slug": fname[:-3],
            "title": headline,
            "path": path,
            "raw": raw,
            "payload": payload,
            "leads": leads,
        })
    return scans


def _signal_class(strength) -> str:
    try:
        n = float(strength)
    except (TypeError, ValueError):
        return ""
    return "positive" if n >= 75 else ("badge-mixed" if n >= 55 else "")


def build_scan_page(scan: dict):
    date = scan["date"]
    leads = scan["leads"]
    payload = scan["payload"]

    if leads:
        lead_html = ""
        for i, lead in enumerate(leads, 1):
            strength = lead.get("signal_strength", "")
            label = lead.get("signal_strength_label", "")
            category = lead.get("category") or lead.get("signal_type") or lead.get("type") or ""
            primary = next((k for k in _LEAD_TITLE_KEYS if lead.get(k)), None)
            skip = _LEAD_HEADER_KEYS | ({primary} if primary else set())
            signal = f'<span class="scan-signal {_signal_class(strength)}">&#9889; {html.escape(str(strength))}{" " + html.escape(str(label)) if label else ""}</span>' if strength != "" else ""
            cat = f'<span class="tag">{html.escape(str(category))}</span>' if category else ""
            lead_html += f"""
<div class="scan-lead">
  <div class="scan-lead-header">
    <span class="scan-rank">#{html.escape(str(lead.get("rank", i)))}</span>
    <span class="scan-lead-title">{html.escape(_lead_title(lead))}</span>
    {signal}
    {cat}
  </div>
  <div class="scan-lead-body">{_render_fields(lead, skip)}</div>
</div>"""
        context = _render_fields(payload, _SCAN_META_KEYS | {"leads"})
        body = f"""
<div class="thesis-meta">
  <span class="meta-date">&#128197; {date}</span>
  <span class="stat">{len(leads)} LEADS</span>
</div>
{f'<div class="scan-headline-context">{context}</div>' if context else ""}
{lead_html}"""
    else:
        body = f'<div class="thesis-body">{_md_to_html(_strip_frontmatter(scan["raw"]))}</div>'

    path = os.path.join(DOCS_DIR, "scans", f"{scan['slug']}.html")
    with open(path, "w") as f:
        f.write(_page(f"Scan: {date}", body,
                      breadcrumb=f'<a href="{_url("/index.html")}">Home</a> &rsaquo; <a href="{_url("/scans/index.html")}">Scans</a>',
                      active_nav="scans"))


def build_scans_index(scans: list[dict]):
    rows = ""
    for s in scans:
        href = _url(f"/scans/{s['slug']}.html")
        n_leads = len(s.get("leads", []))
        lead_titles = html.escape(", ".join(_lead_title(l)[:50] for l in s.get("leads", [])[:2]))
        rows += (
            f'<tr><td><a href="{href}">{s["date"]}</a></td>'
            f'<td>{n_leads}</td>'
            f'<td class="scan-preview">{lead_titles}</td></tr>\n'
        )
    body = f"""
<table class="thesis-table">
  <thead><tr><th>Date</th><th>Leads</th><th>Top Signals</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    path = os.path.join(DOCS_DIR, "scans", "index.html")
    with open(path, "w") as f:
        f.write(_page("All Scans", body, breadcrumb=f'<a href="{_url("/index.html")}">Home</a>', active_nav="scans"))


def _trader_summary(data: dict) -> str:
    if not data["equity"]:
        return ""
    latest, first = data["equity"][-1], data["equity"][0]
    ret = (latest["equity"] / first["equity"] - 1) * 100
    last = data["journal"][0] if data["journal"] else None
    last_html = (f'<p>Latest session: <a href="{_journal_url(last)}">{last["date"]} — '
                 f'{html.escape(last["headline"])}</a></p>') if last else ""
    return f"""
<section>
  <h2>&#9671; Autonomous Trader</h2>
  <div class="about-box">
    <p><strong>{_money(latest["equity"])}</strong> · {_pct_span(ret)} since {first["date"]} ·
    {len(latest.get("positions", []))} positions · <a href="{_url("/portfolio.html")}">portfolio &amp; trade log →</a></p>
    {last_html}
  </div>
</section>"""


def _lab_summary(data: dict) -> str:
    if not data["notebooks"] and not data["registry"]:
        return ""
    promoted = sum(1 for e in data["registry"].values() if e.get("status") == "promoted")
    latest = data["notebooks"][0] if data["notebooks"] else None
    latest_html = (f'<p>Latest session: <a href="{_notebook_url(latest)}">{latest["date"]} — '
                   f'{html.escape(latest["headline"])}</a></p>') if latest else ""
    return f"""
<section>
  <h2>&#9671; Quant Lab</h2>
  <div class="about-box">
    <p>{promoted} promoted signal{"" if promoted == 1 else "s"} · {len(data["registry"])} proposed ·
    {len(data["library"])} library modules · <a href="{_url("/lab/index.html")}">lab &amp; notebook →</a></p>
    {latest_html}
  </div>
</section>"""


def build_index(theses: list[dict], trader_data: dict, lab_data: dict):
    open_t = [t for t in theses if t["status"] == "open"]
    validated = [t for t in theses if t["status"] == "validated"]
    invalidated = [t for t in theses if t["status"] == "invalidated"]
    all_scans = _list_scans()
    recent_scans = all_scans[:10]

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

    scan_rows = ""
    for s in recent_scans:
        href = _url(f"/scans/{s['slug']}.html")
        n_leads = len(s.get("leads", []))
        scan_rows += f'<tr><td><a href="{href}">{s["date"]}</a></td><td>{n_leads} leads</td><td>{html.escape(s["title"][:90])}</td></tr>\n'
    more_link = f' <a href="{_url("/scans/index.html")}" style="font-size:11px;color:var(--link);">→ view all {len(all_scans)}</a>' if len(all_scans) > 10 else ""
    scan_section = f"""
<section>
  <h2>&#9671; Recent Scans{more_link}</h2>
  <table class="thesis-table">
    <thead><tr><th>Date</th><th>Leads</th><th>Headline</th></tr></thead>
    <tbody>{scan_rows}</tbody>
  </table>
</section>""" if scan_rows else ""

    body = f"""
<div class="marquee-wrap"><marquee>&#9830; LIVE RESEARCH &#9830; AUTONOMOUS ANALYSIS &#9830; PATTERN RECOGNITION &#9830; KNOWLEDGE GRAPH UPDATED DAILY &#9830;</marquee></div>

<div class="stats-bar">
  <span class="stat">&#128202; {len(theses)} THESES</span>
  <span class="stat">&#9989; {len(validated)} VALIDATED</span>
  <span class="stat">&#10060; {len(invalidated)} INVALIDATED</span>
  <span class="stat">&#128269; {len(open_t)} OPEN</span>
  <span class="stat">&#128313; {len(all_scans)} SCANS</span>
</div>

{_trader_summary(trader_data)}
{_lab_summary(lab_data)}
{section("Active Investigations", open_t)}
{section("Validated", validated)}
{section("Invalidated", invalidated)}
{scan_section}

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


def _trader_data() -> dict:
    from bot import trader
    ledger = []
    if os.path.exists(trader.LEDGER_PATH):
        with open(trader.LEDGER_PATH) as f:
            ledger = [json.loads(line) for line in f if line.strip()]
    journal = []
    if os.path.exists(trader.JOURNAL_DIR):
        for fname in sorted(os.listdir(trader.JOURNAL_DIR), reverse=True):
            if fname.endswith(".md"):
                with open(os.path.join(trader.JOURNAL_DIR, fname)) as f:
                    raw = f.read()
                headline = raw.splitlines()[0].lstrip("# ").strip() if raw else fname
                journal.append({"date": fname[:-3], "headline": headline, "raw": raw})
    return {
        "equity": trader._load_json(trader.EQUITY_PATH, []),
        "ledger": ledger,
        "journal": journal,
        "strategy": trader._read(trader.STRATEGY_PATH),
        "strategy_history": trader._read(trader.STRATEGY_HISTORY_PATH),
        "directives": trader._load_json(trader.DIRECTIVES_PATH, {}),
    }


def _journal_url(entry: dict) -> str:
    return _url(f"/journal/{entry['date']}.html")


def _safe_md(text: str) -> str:
    return _md_to_html(html.escape(text, quote=False))


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _pct_span(x: float) -> str:
    cls = "positive" if x >= 0 else "negative"
    return f'<span class="{cls}">{x:+.2f}%</span>'


def _equity_chart(points: list[dict]) -> str:
    """Single-series equity line with a dashed inception baseline and hover crosshair."""
    if not points:
        return ""
    w, h, pad_l, pad_r, pad_t, pad_b = 900, 260, 70, 16, 16, 28
    vals = [p["equity"] for p in points]
    base = vals[0]
    lo, hi = min(vals + [base]), max(vals + [base])
    span = (hi - lo) or max(hi * 0.01, 1)
    lo, hi = lo - span * 0.1, hi + span * 0.1
    n = len(points)

    def x(i):
        return pad_l + (w - pad_l - pad_r) * (i / (n - 1) if n > 1 else 0.5)

    def y(v):
        return pad_t + (h - pad_t - pad_b) * (1 - (v - lo) / (hi - lo))

    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    rng = hi - lo
    def tick_fmt(v):
        if rng >= 30000:
            return f"${v / 1000:,.0f}k"
        if rng >= 3000:
            return f"${v / 1000:,.1f}k"
        return f"${v:,.0f}"

    ticks = ""
    for k in range(4):
        v = lo + (hi - lo) * k / 3
        ticks += (f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="eq-grid"/>'
                  f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" class="eq-axis" text-anchor="end">{tick_fmt(v)}</text>')
    xlabels = (f'<text x="{x(0):.1f}" y="{h - 8}" class="eq-axis" text-anchor="start">{points[0]["date"]}</text>'
               + (f'<text x="{x(n - 1):.1f}" y="{h - 8}" class="eq-axis" text-anchor="end">{points[-1]["date"]}</text>' if n > 1 else ""))
    data = json.dumps([{"d": p["date"], "v": p["equity"], "x": round(x(i), 1), "y": round(y(p["equity"]), 1)}
                       for i, p in enumerate(points)])
    last = f'<circle cx="{x(n - 1):.1f}" cy="{y(vals[-1]):.1f}" r="4" class="eq-dot"/>'
    return f"""
<div class="eq-chart" data-points='{html.escape(data)}' data-base="{base}">
  <svg viewBox="0 0 {w} {h}" role="img" aria-label="Account equity over time">
    {ticks}
    <line x1="{pad_l}" x2="{w - pad_r}" y1="{y(base):.1f}" y2="{y(base):.1f}" class="eq-base"/>
    <path d="{path}" class="eq-line"/>
    {last}{xlabels}
    <line class="eq-cross" y1="{pad_t}" y2="{h - pad_b}" x1="0" x2="0" visibility="hidden"/>
    <circle class="eq-hover" r="5" visibility="hidden"/>
    <rect x="{pad_l}" y="0" width="{w - pad_l - pad_r}" height="{h}" fill="transparent" class="eq-hit"/>
  </svg>
  <div class="eq-tip" hidden></div>
</div>
<script>
(function() {{
  const box = document.currentScript.previousElementSibling;
  const pts = JSON.parse(box.dataset.points), base = +box.dataset.base;
  const svg = box.querySelector('svg'), cross = box.querySelector('.eq-cross'),
        dot = box.querySelector('.eq-hover'), tip = box.querySelector('.eq-tip');
  box.querySelector('.eq-hit').addEventListener('mousemove', e => {{
    const r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) * svg.viewBox.baseVal.width / r.width;
    let p = pts[0]; for (const q of pts) if (Math.abs(q.x - vx) < Math.abs(p.x - vx)) p = q;
    cross.setAttribute('x1', p.x); cross.setAttribute('x2', p.x); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', p.x); dot.setAttribute('cy', p.y); dot.setAttribute('visibility', 'visible');
    const ret = (p.v / base - 1) * 100;
    tip.innerHTML = p.d + '<br><b>$' + p.v.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}}) +
      '</b><br>' + (ret >= 0 ? '+' : '') + ret.toFixed(2) + '% since start';
    tip.hidden = false;
    const sx = p.x * r.width / svg.viewBox.baseVal.width;
    tip.style.left = Math.min(sx + 12, r.width - 150) + 'px';
    tip.style.top = (p.y * r.height / svg.viewBox.baseVal.height - 10) + 'px';
  }});
  box.querySelector('.eq-hit').addEventListener('mouseleave', () => {{
    cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); tip.hidden = true;
  }});
}})();
</script>"""


def _ledger_rows(ledger: list[dict]) -> str:
    rows = ""
    for t in reversed(ledger):
        req, o = t.get("request", {}), t.get("order") or {}
        side = (req.get("side") or "close").upper()
        if req.get("qty"):
            size = f"{req['qty']:g} sh"
        elif req.get("notional"):
            size = _money(req["notional"])
        elif req.get("percentage"):
            size = f"{req['percentage']:g}%"
        else:
            size = "all"
        if t.get("error"):
            status = f'<span class="negative">rejected</span>'
        else:
            status = html.escape(o.get("status", "?"))
            if o.get("filled_avg_price"):
                status += f" @ {_money(o['filled_avg_price'])}"
        side_cls = "positive" if side == "BUY" else "negative"
        rows += (f'<tr><td><a href="{_journal_url(t)}">{t["date"]}</a></td>'
                 f'<td class="{side_cls}">{side}</td><td><strong>{html.escape(t.get("symbol", ""))}</strong></td>'
                 f'<td>{size}</td><td>{status}</td><td class="trade-why">{html.escape(t.get("rationale", ""))}'
                 + (f'<br><small class="negative">{html.escape(t["error"][:200])}</small>' if t.get("error") else "")
                 + '</td></tr>\n')
    return rows


def build_portfolio_page(data: dict):
    equity, ledger, journal = data["equity"], data["ledger"], data["journal"]
    if not equity:
        body = ('<div class="about-box"><p>The autonomous trader has not run yet. It runs every weekday after the '
                'market opens (workflow <code>Daily Trading Session</code>), or trigger it manually from GitHub Actions.</p></div>')
        with open(os.path.join(DOCS_DIR, "portfolio.html"), "w") as f:
            f.write(_page("Portfolio", body, active_nav="portfolio"))
        return

    latest, first = equity[-1], equity[0]
    total_ret = (latest["equity"] / first["equity"] - 1) * 100
    day_ret = (latest["equity"] / equity[-2]["equity"] - 1) * 100 if len(equity) > 1 else 0.0
    positions = latest.get("positions", [])

    pos_rows = ""
    for p in sorted(positions, key=lambda p: -abs(p["market_value"])):
        weight = abs(p["market_value"]) / latest["equity"] * 100 if latest["equity"] else 0
        pl_cls = "positive" if p["unrealized_pl"] >= 0 else "negative"
        pos_rows += (f'<tr><td><strong>{html.escape(p["symbol"])}</strong></td><td>{p.get("side", "long")}</td>'
                     f'<td>{p["qty"]:g}</td><td>{_money(p["avg_entry_price"])}</td>'
                     f'<td>{_money(p.get("current_price", 0))}</td><td>{_money(p["market_value"])}</td><td>{weight:.1f}%</td>'
                     f'<td class="{pl_cls}">{_money(p["unrealized_pl"])} ({p["unrealized_plpc"] * 100:+.1f}%)</td></tr>\n')

    directives = data["directives"].get("directives", [])
    dir_html = "".join(
        f'<li><strong>{html.escape(d.get("topic", ""))}</strong> — {html.escape(d.get("why", ""))}'
        + (" " + " ".join(f'<span class="tag">{html.escape(t)}</span>' for t in d.get("tickers") or []) if d.get("tickers") else "")
        + "</li>"
        for d in directives
    )
    journal_rows = "".join(
        f'<tr><td><a href="{_journal_url(j)}">{j["date"]}</a></td><td>{html.escape(j["headline"])}</td></tr>'
        for j in journal[:10]
    )
    eq_rows = "".join(
        f'<tr><td>{e["date"]}</td><td>{_money(e["equity"])}</td><td>{_money(e["cash"])}</td>'
        f'<td>{_pct_span((e["equity"] / first["equity"] - 1) * 100)}</td></tr>'
        for e in reversed(equity)
    )
    ledger_rows = _ledger_rows(ledger)

    body = f"""
<div class="stats-bar">
  <span class="stat">EQUITY: {_money(latest["equity"])}</span>
  <span class="stat">SINCE {first["date"]}: {_pct_span(total_ret)}</span>
  <span class="stat">LAST SESSION: {_pct_span(day_ret)}</span>
  <span class="stat">CASH: {_money(latest["cash"])}</span>
  <span class="stat">{len(positions)} POSITION{"" if len(positions) == 1 else "S"} · {sum(1 for t in ledger if not t.get("error"))} TRADES</span>
</div>

<section>
  <h2>&#9671; Account Equity</h2>
  {_equity_chart(equity)}
  <details class="eq-table"><summary>Show as table</summary>
    <table class="thesis-table"><thead><tr><th>Date</th><th>Equity</th><th>Cash</th><th>Return</th></tr></thead>
    <tbody>{eq_rows}</tbody></table>
  </details>
</section>

<section>
  <h2>&#9671; Positions <small class="meta-date">as of {latest["date"]}</small></h2>
  <table class="thesis-table">
    <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg Entry</th><th>Price</th><th>Value</th><th>Weight</th><th>Unrealized P&amp;L</th></tr></thead>
    <tbody>{pos_rows or '<tr><td colspan="8">All cash</td></tr>'}</tbody>
  </table>
</section>

<section>
  <h2>&#9671; Recent Sessions <a href="{_url("/journal/index.html")}" style="font-size:11px;color:var(--link);">→ full journal</a></h2>
  <table class="thesis-table"><thead><tr><th>Date</th><th>Headline</th></tr></thead><tbody>{journal_rows}</tbody></table>
</section>

<section>
  <h2>&#9671; Current Strategy</h2>
  <div class="thesis-body">{_safe_md(data["strategy"]) if data["strategy"] else "<p>No strategy written yet.</p>"}</div>
  {f'<details class="eq-table"><summary>Strategy change history</summary><div class="thesis-body">{_safe_md(data["strategy_history"])}</div></details>' if data["strategy_history"] else ""}
</section>

<section>
  <h2>&#9671; Research Directives <small class="meta-date">sent to the next scan</small></h2>
  {f'<ul class="directive-list">{dir_html}</ul>' if dir_html else "<p>None.</p>"}
</section>

<section>
  <h2>&#9671; Trade Log</h2>
  <table class="thesis-table">
    <thead><tr><th>Date</th><th>Side</th><th>Symbol</th><th>Size</th><th>Status</th><th>Rationale</th></tr></thead>
    <tbody>{ledger_rows or '<tr><td colspan="6">No trades yet.</td></tr>'}</tbody>
  </table>
  <p class="disclaimer">&#9888; Paper trading account only. Not real money. Not financial advice.</p>
</section>"""
    with open(os.path.join(DOCS_DIR, "portfolio.html"), "w") as f:
        f.write(_page("Portfolio", body, active_nav="portfolio"))


def build_journal_pages(journal: list[dict]):
    crumb = f'<a href="{_url("/portfolio.html")}">Portfolio</a> &rsaquo; <a href="{_url("/journal/index.html")}">Journal</a>'
    for j in journal:
        main_part, _, reasoning = j["raw"].partition("## Full reasoning")
        body = f'<div class="thesis-body">{_safe_md(main_part)}</div>'
        if reasoning.strip():
            body += (f'<details class="eq-table"><summary>Full session reasoning</summary>'
                     f'<div class="thesis-body">{_safe_md(reasoning)}</div></details>')
        with open(os.path.join(DOCS_DIR, "journal", f'{j["date"]}.html'), "w") as f:
            f.write(_page(f'Session {j["date"]}', body, breadcrumb=crumb, active_nav="portfolio"))
    rows = "".join(
        f'<tr><td><a href="{_journal_url(j)}">{j["date"]}</a></td><td>{html.escape(j["headline"])}</td></tr>'
        for j in journal
    )
    body = (f'<table class="thesis-table"><thead><tr><th>Date</th><th>Headline</th></tr></thead>'
            f'<tbody>{rows or "<tr><td colspan=2>No sessions yet.</td></tr>"}</tbody></table>')
    with open(os.path.join(DOCS_DIR, "journal", "index.html"), "w") as f:
        f.write(_page("Trading Journal", body, breadcrumb=f'<a href="{_url("/portfolio.html")}">Portfolio</a>', active_nav="portfolio"))


def _lab_data() -> dict:
    from bot.lab.sandbox import load_library_index
    from bot.lab.session import NOTEBOOK_DIR
    from bot.lab.signals import load_registry
    from bot.lab.data import META_PATH
    notebooks = []
    if os.path.exists(NOTEBOOK_DIR):
        for fname in sorted(os.listdir(NOTEBOOK_DIR), reverse=True):
            if fname.endswith(".md"):
                with open(os.path.join(NOTEBOOK_DIR, fname)) as f:
                    raw = f.read()
                notebooks.append({"date": fname[:-3], "headline": raw.splitlines()[0].lstrip("# ").strip(), "raw": raw})
    meta = {}
    if os.path.exists(META_PATH):
        with open(META_PATH) as f:
            meta = json.load(f)
    return {"registry": load_registry(), "notebooks": notebooks, "library": load_library_index(), "meta": meta}


def _lab_md(text: str) -> str:
    """Markdown with ![alt](figures/x.png) images, rendered safely."""
    images = {}

    def stash(m):
        key = f"@@IMG{len(images)}@@"
        images[key] = f'<img class="lab-fig" src="{_url("/lab/" + m.group(2))}" alt="{m.group(1)}">'
        return key

    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"!\[([^\]]*)\]\((figures/[\w.\-]+\.png)\)", stash, escaped)
    out = _md_to_html(escaped)
    for key, tag in images.items():
        out = out.replace(key, tag)
    return out


def _sharpe(x) -> str:
    if x is None:
        return "—"
    cls = "positive" if x >= 0.5 else ("negative" if x < 0 else "")
    return f'<span class="{cls}">{x:.2f}</span>'


def _notebook_url(entry: dict) -> str:
    return _url(f"/lab/notebook/{entry['date']}.html")


def build_lab_pages(data: dict):
    reg, notebooks, library, meta = data["registry"], data["notebooks"], data["library"], data["meta"]
    by_status = {}
    for e in reg.values():
        by_status.setdefault(e.get("status", "?"), []).append(e)

    promoted_html = ""
    for e in by_status.get("promoted", []):
        ev = e["evaluation"]
        curve = [{"date": d, "equity": v * 10000} for d, v in ev.get("equity_curve", [])]
        weights = " ".join(f'<span class="tag">{html.escape(k)} {v:+.0%}</span>' for k, v in list(ev["current_weights"].items())[:12])
        promoted_html += f"""
<div class="scan-lead">
  <div class="scan-lead-header">
    <span class="scan-lead-title">{html.escape(e["name"])}</span>
    <span class="badge badge-bull">PROMOTED {e["promoted"]}</span>
  </div>
  <div class="scan-lead-body">
    <p>{html.escape(e.get("description", ""))}</p>
    <p><strong>Why it should work:</strong> {html.escape(e.get("hypothesis", ""))}</p>
    <p><strong>Sharpe</strong> in-sample {_sharpe(ev["insample"]["sharpe"])} · holdout {_sharpe(ev["holdout"]["sharpe"])} ·
       live {_sharpe(ev["live"]["sharpe"]) if ev["live"]["days"] else "—"} ({ev["live"]["days"]} days) ·
       holdout max drawdown {ev["holdout"]["max_drawdown"]:.1%}</p>
    <p><strong>Current targets ({ev["as_of"]}):</strong> {weights or "flat"}</p>
    <details class="eq-table"><summary>Backtest: growth of $10,000 (net of costs)</summary>{_equity_chart(curve)}</details>
  </div>
</div>"""

    rows = ""
    for e in sorted(reg.values(), key=lambda e: e.get("proposed", ""), reverse=True):
        ev = e.get("evaluation") or {}
        status = e.get("status", "?")
        badge = {"promoted": "badge-bull", "rejected": "badge-bear", "retired": "badge-mixed"}.get(status, "badge-neutral")
        reasons = "; ".join(e.get("reasons") or [])
        rows += (f'<tr><td><strong>{html.escape(e["name"])}</strong><br><small>{html.escape(e.get("description", "")[:160])}</small></td>'
                 f'<td><span class="badge {badge}">{status.upper()}</span></td><td>{e.get("proposed", "")}</td>'
                 f'<td>{_sharpe(ev.get("insample", {}).get("sharpe"))}</td><td>{_sharpe(ev.get("holdout", {}).get("sharpe"))}</td>'
                 f'<td class="trade-why">{html.escape(reasons)}</td></tr>')

    nb_rows = "".join(
        f'<tr><td><a href="{_notebook_url(n)}">{n["date"]}</a></td><td>{html.escape(n["headline"])}</td></tr>' for n in notebooks
    )
    lib_rows = "".join(
        f'<tr><td><code>library.{html.escape(k)}</code></td><td>{html.escape(v["description"])}</td></tr>' for k, v in library.items()
    )
    coverage = (f'{meta.get("symbols", "?")} symbols · {meta.get("first_date", "?")} → {meta.get("last_date", "?")}'
                if meta else "price store not built yet")

    body = f"""
<div class="stats-bar">
  <span class="stat">&#9989; {len(by_status.get("promoted", []))} PROMOTED</span>
  <span class="stat">&#10060; {len(by_status.get("rejected", []))} REJECTED</span>
  <span class="stat">&#9851; {len(by_status.get("retired", []))} RETIRED</span>
  <span class="stat">&#128218; {len(library)} LIBRARY MODULES</span>
  <span class="stat">&#128190; {coverage}</span>
</div>

<div class="about-box">
  <p>The lab writes and runs its own Python against daily price history to test market hypotheses. Trading signals it
  proposes must pass a lookahead check and beat the gate on the most recent year of data, which its research never sees.
  Promoted signals are handed to the portfolio manager daily and retired automatically if their live record decays.</p>
</div>

<section>
  <h2>&#9671; Promoted Signals</h2>
  {promoted_html or "<p>None yet. Most ideas fail out of sample — that is the gate working.</p>"}
</section>

<section>
  <h2>&#9671; Lab Notebook</h2>
  <table class="thesis-table"><thead><tr><th>Date</th><th>Session</th></tr></thead>
  <tbody>{nb_rows or '<tr><td colspan="2">No sessions yet.</td></tr>'}</tbody></table>
</section>

<section>
  <h2>&#9671; Every Signal Ever Proposed</h2>
  <table class="thesis-table">
    <thead><tr><th>Signal</th><th>Status</th><th>Proposed</th><th>In-sample Sharpe</th><th>Holdout Sharpe</th><th>Gate notes</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="6">Nothing proposed yet.</td></tr>'}</tbody>
  </table>
</section>

<section>
  <h2>&#9671; Library</h2>
  <table class="thesis-table"><thead><tr><th>Module</th><th>What it does</th></tr></thead>
  <tbody>{lib_rows or '<tr><td colspan="2">Empty.</td></tr>'}</tbody></table>
</section>"""
    with open(os.path.join(DOCS_DIR, "lab", "index.html"), "w") as f:
        f.write(_page("Quant Lab", body, active_nav="lab"))

    crumb = f'<a href="{_url("/lab/index.html")}">Lab</a>'
    for n in notebooks:
        main_part, _, log = n["raw"].partition("## Session log")
        body = f'<div class="thesis-body">{_lab_md(main_part)}</div>'
        if log.strip():
            body += (f'<details class="eq-table"><summary>Full session log</summary>'
                     f'<div class="thesis-body">{_safe_md(log)}</div></details>')
        with open(os.path.join(DOCS_DIR, "lab", "notebook", f'{n["date"]}.html'), "w") as f:
            f.write(_page(f'Lab {n["date"]}', body, breadcrumb=crumb, active_nav="lab"))


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

/* SCAN PAGES */
.scan-headline-context {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent2);
  padding: 12px 16px;
  margin-bottom: 20px;
  font-size: 13px;
  color: var(--text);
  line-height: 1.7;
}

.scan-lead {
  background: rgba(0,0,44,0.5);
  border: 1px solid #001144;
  border-left: 3px solid var(--border);
  margin-bottom: 20px;
}

.scan-lead-header {
  background: var(--bg2);
  border-bottom: 1px solid #001144;
  padding: 8px 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.scan-rank {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #556688;
  min-width: 24px;
}

.scan-lead-title {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-bright);
  flex: 1;
}

.scan-signal {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: bold;
  padding: 2px 8px;
  background: rgba(0,85,255,0.15);
  border: 1px solid var(--border);
  color: var(--border2);
}
.scan-signal.positive { background: rgba(0,255,136,0.1); border-color: var(--bull); color: var(--bull); }
.scan-signal.badge-mixed { background: rgba(255,102,0,0.1); border-color: var(--accent2); color: var(--accent2); }

.scan-lead-body {
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.7;
}
.scan-lead-body p { margin-bottom: 10px; }
.scan-lead-body strong { color: var(--border2); }

.scan-invest, .scan-sources {
  margin-top: 8px;
  font-size: 12px;
  color: #8899bb;
}
.scan-invest ul, .scan-sources ul { margin-top: 4px; padding-left: 16px; }
.scan-invest li, .scan-sources li { margin: 2px 0; }

.scan-preview { color: #556688; font-size: 12px; }

/* TRADER */
.eq-chart { position: relative; background: var(--bg3); border: 1px solid var(--border); padding: 8px; }
.eq-chart svg { width: 100%; height: auto; display: block; }
.eq-grid { stroke: #0a1a44; stroke-width: 1; }
.eq-axis { fill: #6677aa; font-family: var(--font-mono); font-size: 11px; }
.eq-base { stroke: #556688; stroke-width: 1; stroke-dasharray: 4 4; }
.eq-line { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; }
.eq-dot, .eq-hover { fill: var(--accent); stroke: var(--bg3); stroke-width: 2; }
.eq-cross { stroke: var(--border2); stroke-width: 1; }
.eq-tip {
  position: absolute; pointer-events: none; background: var(--bg2); border: 1px solid var(--border2);
  padding: 6px 10px; font-family: var(--font-mono); font-size: 11px; color: var(--text); line-height: 1.5;
}
.eq-tip b { color: var(--text-bright); }
.eq-table { margin-top: 8px; font-size: 12px; }
.eq-table summary { cursor: pointer; color: var(--link); font-family: var(--font-mono); font-size: 11px; margin-bottom: 6px; }
.trade-why { font-size: 12px; color: var(--text); max-width: 420px; }
.directive-list { padding-left: 18px; }
.directive-list li { margin: 6px 0; }

.lab-fig { max-width: 100%; border: 1px solid var(--border); background: #fff; margin: 8px 0; display: block; }

.scan-field { margin-bottom: 10px; }
.scan-field ul, .scan-lead-body ul ul, .scan-headline-context ul { margin: 4px 0 0 0; padding-left: 18px; }
.scan-field li { margin: 2px 0; }
.scan-headline-context p { margin-bottom: 8px; }
.scan-headline-context strong { color: var(--accent); }

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

    # Scan pages
    all_scans = _list_scans()
    for scan in all_scans:
        build_scan_page(scan)
    build_scans_index(all_scans)

    build_theses_index(theses)
    build_connections_index()
    build_validations_index()
    trader_data = _trader_data()
    build_portfolio_page(trader_data)
    build_journal_pages(trader_data["journal"])
    lab_data = _lab_data()
    build_lab_pages(lab_data)
    build_index(theses, trader_data, lab_data)

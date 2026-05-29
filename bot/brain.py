"""
Manages the markdown knowledge graph in brain/.

Structure:
  brain/
    index.md                  - master index of all theses + connections
    theses/<slug>.md          - individual thesis deep-dive
    connections/<slug>.md     - cross-thesis connection notes
    validations/<slug>.md     - lookback validation results
    assets/<slug>_data.md     - raw data snapshots used in analysis
"""

import os
import re
import json
from datetime import datetime, date
from typing import Optional
from bot.config import BRAIN_DIR, THESES_DIR, CONNECTIONS_DIR, VALIDATIONS_DIR, ASSETS_DIR


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _ensure_dirs():
    for d in [THESES_DIR, CONNECTIONS_DIR, VALIDATIONS_DIR, ASSETS_DIR]:
        os.makedirs(d, exist_ok=True)


def list_theses() -> list[dict]:
    _ensure_dirs()
    theses = []
    for fname in sorted(os.listdir(THESES_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(THESES_DIR, fname)
        meta = _read_frontmatter(path)
        theses.append({
            "slug": fname[:-3],
            "path": path,
            "title": meta.get("title", fname[:-3]),
            "status": meta.get("status", "open"),
            "created": meta.get("created", ""),
            "tags": meta.get("tags", []),
            "verdict": meta.get("verdict", ""),
        })
    return theses


def get_thesis(slug: str) -> Optional[str]:
    path = os.path.join(THESES_DIR, f"{slug}.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return None


def save_thesis(title: str, content: str, tags: list[str] = None, status: str = "open") -> str:
    _ensure_dirs()
    slug = _slug(title)
    path = os.path.join(THESES_DIR, f"{slug}.md")
    tags_str = json.dumps(tags or [])
    frontmatter = f"""---
title: {title}
slug: {slug}
created: {_now()}
updated: {_now()}
status: {status}
tags: {tags_str}
verdict: ""
---

"""
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(frontmatter + content)
    else:
        existing = _read_raw(path)
        updated = _update_frontmatter_field(existing, "updated", _now())
        updated = _update_frontmatter_field(updated, "status", status)
        with open(path, "w") as f:
            f.write(updated + "\n\n---\n\n## Update " + _now() + "\n\n" + content)
    _rebuild_index()
    return slug


def save_validation(thesis_slug: str, content: str, verdict: str) -> str:
    _ensure_dirs()
    slug = f"{thesis_slug}-validation-{_now()}"
    path = os.path.join(VALIDATIONS_DIR, f"{slug}.md")
    with open(path, "w") as f:
        f.write(f"""---
thesis: {thesis_slug}
date: {_now()}
verdict: {verdict}
---

# Validation: {thesis_slug}
*Run date: {_now()}*

{content}
""")
    # Update thesis verdict
    thesis_path = os.path.join(THESES_DIR, f"{thesis_slug}.md")
    if os.path.exists(thesis_path):
        raw = _read_raw(thesis_path)
        raw = _update_frontmatter_field(raw, "verdict", verdict)
        raw = _update_frontmatter_field(raw, "updated", _now())
        with open(thesis_path, "w") as f:
            f.write(raw)
    _rebuild_index()
    return slug


def save_connection(title: str, thesis_slugs: list[str], content: str) -> str:
    _ensure_dirs()
    slug = _slug(title)
    path = os.path.join(CONNECTIONS_DIR, f"{slug}.md")
    links = " ".join(f"[[{s}]]" for s in thesis_slugs)
    with open(path, "w") as f:
        f.write(f"""---
title: {title}
created: {_now()}
linked_theses: {json.dumps(thesis_slugs)}
---

# {title}
*Created: {_now()}*

**Related theses:** {links}

{content}
""")
    _rebuild_index()
    return slug


def save_asset(slug: str, content: str):
    _ensure_dirs()
    path = os.path.join(ASSETS_DIR, f"{slug}.md")
    with open(path, "w") as f:
        f.write(f"# Data Asset: {slug}\n*Captured: {_now()}*\n\n{content}\n")


def _rebuild_index():
    theses = list_theses()
    connections = []
    for fname in sorted(os.listdir(CONNECTIONS_DIR)):
        if fname.endswith(".md"):
            connections.append(fname[:-3])
    validations = []
    for fname in sorted(os.listdir(VALIDATIONS_DIR)):
        if fname.endswith(".md"):
            validations.append(fname[:-3])

    lines = [
        "# Andiamo Brain — Knowledge Index",
        f"*Last updated: {_now()}*",
        "",
        "## Theses",
        "",
    ]
    status_order = {"open": 0, "validated": 1, "invalidated": 2, "stale": 3}
    for t in sorted(theses, key=lambda x: status_order.get(x["status"], 9)):
        verdict = f" · {t['verdict']}" if t.get("verdict") else ""
        tags = ", ".join(t["tags"]) if t.get("tags") else ""
        lines.append(f"- [[{t['slug']}]] — **{t['status']}**{verdict} | {tags}")
    lines += ["", "## Connections", ""]
    for c in connections:
        lines.append(f"- [[{c}]]")
    lines += ["", "## Validations", ""]
    for v in validations:
        lines.append(f"- [[{v}]]")

    with open(os.path.join(BRAIN_DIR, "index.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def _read_raw(path: str) -> str:
    with open(path) as f:
        return f.read()


def _read_frontmatter(path: str) -> dict:
    meta = {}
    try:
        with open(path) as f:
            content = f.read()
        if not content.startswith("---"):
            return meta
        end = content.index("---", 3)
        block = content[3:end].strip()
        for line in block.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                v = v.strip()
                try:
                    meta[k.strip()] = json.loads(v)
                except Exception:
                    meta[k.strip()] = v
    except Exception:
        pass
    return meta


def _update_frontmatter_field(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^({re.escape(key)}:\s*)(.*)$", re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(rf"\g<1>{value}", content)
    # Insert after first ---
    return content.replace("---\n", f"---\n{key}: {value}\n", 1)

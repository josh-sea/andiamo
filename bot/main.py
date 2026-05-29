"""
CLI entry point.

Usage:
  python -m bot.main investigate "copper supply thesis"
  python -m bot.main validate "copper supply thesis"
  python -m bot.main lookback "copper supply thesis" --date 2024-01-15
  python -m bot.main scan "semiconductor sector"
  python -m bot.main build-site
  python -m bot.main show-brain
  python -m bot.main daily-scan
"""

import sys
import json
import argparse
from datetime import datetime

from bot import investigator, brain
from bot.site import builder as site_builder


def cmd_investigate(args):
    hypothesis = " ".join(args.hypothesis)
    print(f"\n[andiamo] Investigating: {hypothesis}\n")
    result = investigator.run_and_save(
        hypothesis,
        mode="full",
        paper_trade=args.trade,
        verbose=True,
    )
    s = result.get("structured", {})
    print("\n" + "=" * 60)
    print(f"VERDICT: {s.get('verdict', 'n/a').upper()}  |  CONFIDENCE: {s.get('confidence', '?')}/100")
    print(f"Summary: {s.get('summary', '')}")
    if result.get("brain_slug"):
        print(f"Saved to brain: brain/theses/{result['brain_slug']}.md")
    if result.get("order"):
        print(f"Paper trade placed: {result['order']}")
    site_builder.build()
    print("[andiamo] Site rebuilt.")


def cmd_validate(args):
    hypothesis = " ".join(args.hypothesis)
    print(f"\n[andiamo] Validating: {hypothesis}\n")
    result = investigator.run_and_save(hypothesis, mode="validate", verbose=True)
    s = result.get("structured", {})
    print("\n" + "=" * 60)
    print(f"VERDICT: {s.get('verdict', 'n/a')}")
    site_builder.build()


def cmd_lookback(args):
    hypothesis = " ".join(args.hypothesis)
    date = args.date
    print(f"\n[andiamo] Lookback analysis: {hypothesis} @ {date}\n")
    result = investigator.run_and_save(hypothesis, mode="lookback", lookback_date=date, verbose=True)
    s = result.get("structured", {})
    print("\n" + "=" * 60)
    print(f"VERDICT: {s.get('verdict', 'n/a')}  |  CONFIDENCE: {s.get('confidence', '?')}/100")
    site_builder.build()


def cmd_scan(args):
    topic = " ".join(args.topic)
    print(f"\n[andiamo] Scanning: {topic}\n")
    result = investigator.investigate(topic, mode="scan", verbose=True)
    print("\n" + "=" * 60)
    print(result["full_text"][-2000:])
    site_builder.build()


def cmd_daily_scan(args):
    print(f"\n[andiamo] Daily scan — {datetime.utcnow().date()}\n")
    from bot.sources.reddit import get_top_finance_posts
    posts = get_top_finance_posts(limit_per_sub=10)
    top_titles = [p["title"] for p in posts[:20] if not p.get("error")]
    digest = "\n".join(f"- {t}" for t in top_titles)
    hypothesis = f"Daily finance signal scan for {datetime.utcnow().date()}:\n{digest}"
    result = investigator.run_and_save(hypothesis, mode="scan", verbose=True)
    site_builder.build()
    print("[andiamo] Daily scan complete. Site rebuilt.")


def cmd_build_site(args):
    site_builder.build()
    print("[andiamo] Site built in docs/")


def cmd_show_brain(args):
    import os
    from bot.config import BRAIN_DIR
    index_path = os.path.join(BRAIN_DIR, "index.md")
    if os.path.exists(index_path):
        with open(index_path) as f:
            print(f.read())
    else:
        print("Brain is empty. Run an investigation first.")
    theses = brain.list_theses()
    print(f"\n{len(theses)} theses in knowledge graph.")


def main():
    parser = argparse.ArgumentParser(prog="andiamo", description="Agentic finance research bot")
    sub = parser.add_subparsers(dest="command")

    p_inv = sub.add_parser("investigate", help="Deep-dive a hypothesis")
    p_inv.add_argument("hypothesis", nargs="+")
    p_inv.add_argument("--trade", action="store_true", help="Place paper trade if confidence >= 65")

    p_val = sub.add_parser("validate", help="Validate an existing thesis")
    p_val.add_argument("hypothesis", nargs="+")

    p_lb = sub.add_parser("lookback", help="Analyze hypothesis date-filtered to a past date")
    p_lb.add_argument("hypothesis", nargs="+")
    p_lb.add_argument("--date", required=True, help="YYYY-MM-DD")

    p_scan = sub.add_parser("scan", help="Surface scan a topic for signals")
    p_scan.add_argument("topic", nargs="+")

    sub.add_parser("daily-scan", help="Run the daily scan pipeline")
    sub.add_parser("build-site", help="Rebuild the GitHub Pages site")
    sub.add_parser("show-brain", help="Print the knowledge graph index")

    args = parser.parse_args()

    dispatch = {
        "investigate": cmd_investigate,
        "validate": cmd_validate,
        "lookback": cmd_lookback,
        "scan": cmd_scan,
        "daily-scan": cmd_daily_scan,
        "build-site": cmd_build_site,
        "show-brain": cmd_show_brain,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

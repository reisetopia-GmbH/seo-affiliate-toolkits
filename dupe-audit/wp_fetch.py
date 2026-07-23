# -*- coding: utf-8 -*-
"""Fetch a set of WordPress pages/posts through the public REST API into one JSON file.

Usage:
  python wp_fetch.py <site> <slugs.txt> [out.json] [--posts] [--contains SUBSTRING]

  <site>        https://example.com
  <slugs.txt>   one slug per line (blank lines and #comments ignored)
  --posts       query /wp/v2/posts instead of /wp/v2/pages
  --contains    when a slug exists in several directories, keep the hit whose
                link contains this substring (e.g. --contains /guides/)

Output: {slug: {"id":…, "link":…, "html": rendered content}} — the input for dupe_scan.py.

Deliberately sequential with a delay: a duplicate audit is a bulk read of someone's
production site, including your own. Hammering it in parallel is how you get rate limited
or, worse, how you add load to a live site during business hours.
"""
import io
import json
import sys
import time

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
DELAY = 0.7  # seconds between requests


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    site = args[0].rstrip("/")
    slug_file = args[1]
    out_file = args[2] if len(args) > 2 else "pages.json"
    endpoint = "posts" if "--posts" in flags else "pages"
    contains = next((f.split("=", 1)[1] for f in flags if f.startswith("--contains=")), None)

    slugs = [
        ln.strip()
        for ln in open(slug_file, encoding="utf-8-sig")  # tolerate a BOM on Windows
        if ln.strip() and not ln.startswith("#")
    ]
    print(f"{len(slugs)} slugs to fetch from {site}", file=sys.stderr)

    out, fails = {}, []
    for i, s in enumerate(slugs):
        try:
            r = requests.get(
                f"{site}/wp-json/wp/v2/{endpoint}",
                params={"slug": s, "_fields": "id,link,content"},
                headers=UA,
                timeout=60,
            )
            arr = r.json()
            # A slug is only unique per post type, not per directory: /a/x/ and /b/x/
            # both answer to slug=x. Without --contains you may silently analyse the
            # wrong page, which is very hard to notice later.
            page = None
            if contains:
                page = next((p for p in arr if contains in p["link"]), None)
            if page is None:
                page = arr[0] if arr else None
                if contains and page:
                    print(f"  ! {s}: no link matched {contains}, using {page['link']}", file=sys.stderr)
            if page:
                out[s] = {"id": page["id"], "link": page["link"], "html": page["content"]["rendered"]}
            else:
                fails.append(s)
        except Exception as e:  # network, JSON, shape — all just mean "retry this one by hand"
            fails.append(f"{s} ({type(e).__name__})")
        time.sleep(DELAY)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(slugs)}", file=sys.stderr)

    json.dump(out, open(out_file, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"OK: {len(out)} fetched into {out_file}. Failed: {fails}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()

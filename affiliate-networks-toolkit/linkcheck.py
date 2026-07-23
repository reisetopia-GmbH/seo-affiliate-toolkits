#!/usr/bin/env python3
"""Resolve the FULL redirect chain of affiliate links and classify each one.

Usage:
  python linkcheck.py <links.csv> <results.csv> [options]     # batch mode
  python linkcheck.py <single-url>                            # print one chain, no files

Options:
  --own-domain=example.com   a redirect that ends back on this domain is a soft-404
                             (typical failure mode of link-cloaking plugins: the target
                             is gone, the plugin falls back to your own homepage, the
                             HTTP status chain is all clean 301/200)
  --url-column=url           column with the URLs (default: first header containing
                             "url", else the first column; headerless files work too)
  --max-hops=15              stop following redirects after this many hops
  --timeout=10               per-request timeout in seconds
  --delay=0.3                pause between links (be polite to redirect endpoints)

Input CSV is read BOM-tolerantly (utf-8-sig) — Excel exports just work.

Output columns:
  url, classification, network, http_status, hop_count, hops, final_url, notes

Classifications:
  network:<name>      a hop passed through a known affiliate-network host
  dead-network:<name> a hop points at a network that no longer exists (e.g. zanox);
                      where possible the original target is recovered from the URL
  soft-404            chain ends back on --own-domain (link target is gone)
  broken              final status 404/410/5xx
  unreachable         DNS/connection failure on the first hop
  possible-params     no network host in the chain, but the final URL carries
                      affiliate-looking query parameters (partner_id, clickid, ...).
                      Some merchants track on their own domain via query params only —
                      a host-based classifier alone will misfile these as "no affiliate".
  no-affiliate        none of the above

Why record every hop and not just the final URL: two links can land on the SAME final
page while only one of them credits you. Meta/sub networks and mis-built links are only
visible in the intermediate hops. Judge the chain, not the destination.

Requires: pip install requests
"""
import csv
import re
import sys
import time
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Some affiliate/CDN endpoints refuse non-browser clients — use a browser-ish UA.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Known live network hosts (suffix match against each hop's hostname).
# Extend freely — the mechanism matters more than the list.
NETWORK_HOSTS = {
    "awin": ["awin1.com", "tidd.ly"],
    "cj": ["tkqlhce.com", "dpbolvw.net", "anrdoezrs.net", "jdoqocy.com", "kqzyfj.com"],
    # Impact uses per-advertiser vanity domains; these are common TLD patterns.
    "impact": ["sjv.io", "pxf.io", "hmxg.net", "jyeh.net", "elfm.net", "vkuz.net",
               "xmav.net", "tcux.net"],
    "webgains": ["track.webgains.com"],
    "tradedoubler": ["clk.tradedoubler.com", "clkde.tradedoubler.com", "tradedoubler.com"],
    "digidip": ["visit.digidip.net", "digidip.net"],
    "sovrn": ["redirect.viglink.com", "viglink.com"],
    "skimlinks": ["go.skimresources.com", "skimresources.com"],
    "partnerize": ["prf.hn"],
    "rakuten": ["click.linksynergy.com", "linksynergy.com"],
    "belboon": ["webmasterplan.com"],
    "financeads": ["financeads.net"],
    "daisycon": ["daisycon.io"],
}

# Networks that are shut down: connections fail or links dead-end, so every link
# pointing there is silently unmonetised. Classified separately so they can be migrated.
DEAD_NETWORK_HOSTS = {
    "zanox": ["ad.zanox.com", "zanox-affiliate.de", "ad.zanox-affiliate.de"],
    "shareasale": ["shareasale.com"],
}

# Query parameters that suggest merchant-side affiliate tracking on the final URL.
# ("ref" alone is too noisy to include.)
AFFILIATE_PARAMS = {
    "partner_id", "partnerid", "aff", "aff_id", "affid", "affiliate", "affiliate_id",
    "clickid", "click_id", "irclickid", "cjevent", "awc", "wgu", "tduid", "zanpid",
    "camref", "pubref", "sub_id", "subid", "utm_medium=affiliate",
}


def host_of(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def match_network(hostname, table):
    for network, hosts in table.items():
        for h in hosts:
            if hostname == h or hostname.endswith("." + h):
                return network
    return None


def recover_dead_target(url):
    """Best-effort recovery of the original destination from a dead zanox-style URL.

    Dead zanox URLs carry their target in the `ulp=` query parameter, usually
    DOUBLE-percent-encoded. Some additionally wrap a Partnerize-style
    `destination:<encoded-url>` sub-parameter inside that. Peeling both layers
    recovers the merchant URL so the link can be rebuilt on a living network.
    """
    try:
        qs = parse_qs(urlparse(url).query)
    except ValueError:
        return ""
    ulp = (qs.get("ulp") or qs.get("ULP") or [""])[0]
    if not ulp:
        return ""
    target = unquote(unquote(ulp))
    m = re.search(r"destination:(.*)", target)
    if m:
        target = unquote(m.group(1))
    return target if target.startswith("http") else ""


def resolve_chain(url, max_hops, timeout, session):
    """Follow redirects manually, recording EVERY hop. Returns (hops, final_status, error).

    hops is a list of (status_or_'start', url). We use GET with stream=True rather than
    HEAD: several affiliate endpoints answer HEAD differently (or from cache) and the
    body is closed unread anyway.
    """
    hops = [("start", url)]
    current = url
    status = None
    for _ in range(max_hops):
        try:
            r = session.get(current, allow_redirects=False, timeout=timeout, stream=True)
        except requests.RequestException as e:
            return hops, None, type(e).__name__
        status = r.status_code
        location = r.headers.get("Location")
        r.close()
        if status in (301, 302, 303, 307, 308) and location:
            current = urljoin(current, location)
            hops.append((status, current))
            continue
        return hops, status, None
    return hops, status, "max-hops-exceeded"


def classify(url, hops, final_status, error, own_domain):
    """Return (classification, network, notes)."""
    notes = []

    # 1. Dead networks first — recognisable from the URL even when nothing connects.
    for _, hop_url in hops:
        dead = match_network(host_of(hop_url), DEAD_NETWORK_HOSTS)
        if dead:
            recovered = recover_dead_target(hop_url)
            if recovered:
                notes.append(f"recovered target: {recovered}")
            return f"dead-network:{dead}", dead, "; ".join(notes)

    if error and len(hops) == 1:
        return "unreachable", "", error

    # 2. Which live network (if any) appears anywhere in the chain?
    network = ""
    for _, hop_url in hops:
        n = match_network(host_of(hop_url), NETWORK_HOSTS)
        if n:
            network = network or n
            if n != network:
                notes.append(f"second network in chain: {n}")

    final_url = hops[-1][1]
    final_host = host_of(final_url)

    # 3. Soft-404: the chain ends back on our own domain. Status codes look healthy,
    #    but the visitor never reaches a merchant.
    if own_domain and (final_host == own_domain or final_host.endswith("." + own_domain)):
        start_host = host_of(url)
        if len(hops) > 1 or start_host != final_host:
            return "soft-404", network, "; ".join(notes)

    # 4. Hard breakage.
    if error:
        return "broken", network, "; ".join(notes + [error])
    if final_status and (final_status == 404 or final_status == 410 or final_status >= 500):
        return "broken", network, "; ".join(notes)

    if network:
        return f"network:{network}", network, "; ".join(notes)

    # 5. No network host — but does the final URL track via query parameters?
    try:
        qs = {k.lower() for k in parse_qs(urlparse(final_url).query)}
    except ValueError:
        qs = set()
    hit = qs & AFFILIATE_PARAMS
    if hit:
        return "possible-params", "", "; ".join(notes + [f"params: {','.join(sorted(hit))}"])

    return "no-affiliate", "", "; ".join(notes)


def read_urls(path, url_column):
    """Read the input CSV BOM-tolerantly. Works with or without a header row."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    rows = [r for r in rows if r and any(c.strip() for c in r)]
    if not rows:
        return []
    first = rows[0]
    if any(c.strip().lower().startswith(("http://", "https://")) for c in first):
        # headerless: take the first URL-looking cell of each row
        urls = []
        for r in rows:
            for c in r:
                if c.strip().lower().startswith(("http://", "https://")):
                    urls.append(c.strip())
                    break
        return urls
    # header row: pick the requested column, else the first containing "url", else col 0
    header = [h.strip().lower() for h in first]
    if url_column and url_column.lower() in header:
        idx = header.index(url_column.lower())
    else:
        idx = next((i for i, h in enumerate(header) if "url" in h), 0)
    return [r[idx].strip() for r in rows[1:] if len(r) > idx and r[idx].strip()]


def get_flag(name, default, cast=str):
    for a in sys.argv[1:]:
        if a.startswith(f"--{name}="):
            return cast(a.split("=", 1)[1])
    return default


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return

    own_domain = get_flag("own-domain", "").lower().lstrip(".")
    max_hops = get_flag("max-hops", 15, int)
    timeout = get_flag("timeout", 10, float)
    delay = get_flag("delay", 0.3, float)

    session = requests.Session()
    session.headers["User-Agent"] = UA

    # Single-URL mode: print the chain, human-readable.
    if args[0].lower().startswith(("http://", "https://")):
        url = args[0]
        hops, final_status, error = resolve_chain(url, max_hops, timeout, session)
        cls, network, notes = classify(url, hops, final_status, error, own_domain)
        for status, hop_url in hops:
            print(f"  [{status}] {hop_url}")
        print(f"\nclassification: {cls}")
        if notes:
            print(f"notes: {notes}")
        return

    if len(args) < 2:
        sys.exit("Usage: python linkcheck.py <links.csv> <results.csv> [options]")
    in_path, out_path = args[0], args[1]
    urls = read_urls(in_path, get_flag("url-column", ""))
    if not urls:
        sys.exit(f"No URLs found in {in_path}")

    counts = {}
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "classification", "network", "http_status",
                    "hop_count", "hops", "final_url", "notes"])
        for i, url in enumerate(urls, 1):
            hops, final_status, error = resolve_chain(url, max_hops, timeout, session)
            cls, network, notes = classify(url, hops, final_status, error, own_domain)
            counts[cls] = counts.get(cls, 0) + 1
            chain = " -> ".join(hop_url for _, hop_url in hops)
            w.writerow([url, cls, network, final_status or "",
                        len(hops) - 1, chain, hops[-1][1], notes])
            print(f"[{i}/{len(urls)}] {cls:<22} {url[:90]}")
            if delay:
                time.sleep(delay)

    print(f"\nWrote {out_path}")
    for cls in sorted(counts):
        print(f"  {counts[cls]:>5}  {cls}")


if __name__ == "__main__":
    main()

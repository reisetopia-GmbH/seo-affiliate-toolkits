#!/usr/bin/env python3
"""Affiliate network toolkit: one CLI for AWIN, CJ, Impact, Tradedoubler, Webgains and Sovrn.

Usage:
  python afftool.py awin joined                            -> programmes you are partnered with
  python afftool.py awin programmes [--relationship=notjoined] [--country=DE]
  python afftool.py awin deeplink <programme-id> <target-url>
  python afftool.py cj joined                              -> joined advertisers
  python afftool.py cj programmes --query=<text>           -> search the advertiser directory
  python afftool.py cj links <advertiser-id>               -> ready-made tracking links (clickUrl!)
  python afftool.py cj deeplink <target-url>               -> /type/dlg/ deeplink (no programme id needed)
  python afftool.py impact joined                          -> joined campaigns (Impact has no discovery API)
  python afftool.py impact deeplink <program-id> <target-url>   (ALWAYS live-test the result)
  python afftool.py tradedoubler vouchers                  -> voucher list (site token)
  python afftool.py tradedoubler feeds                     -> product feed list (site token)
  python afftool.py webgains programmes [--name=<text>]    -> full merchant directory (no publisher id needed)
  python afftool.py webgains joined                        -> your programme memberships
  python afftool.py webgains deeplink <programme-id> <target-url>
  python afftool.py sovrn wrap <url>                       -> redirect.viglink.com wrapper link
  python afftool.py sovrn check <url> [--geo=de]           -> "is this URL monetisable?" lookup

Global flag: --format=json|csv   (default json, applies to list-returning commands)

Configuration (environment variables — never put these in files or scripts):
  AWIN_TOKEN             AWIN personal access token (ui.awin.com/awin-api, needs admin right)
  AWIN_PUBLISHER_ID      your AWIN publisher account id (= awinaffid in links)
  CJ_TOKEN               CJ personal access token (developers.cj.com/account/personal-access-tokens)
  CJ_CID                 CJ company id (requestor-cid, for advertiser lookup)
  CJ_WEBSITE_ID          CJ website id / PID (for link search and deeplinks)
  IMPACT_ACCOUNT_SID     Impact account SID (basic auth username)
  IMPACT_AUTH_TOKEN      Impact auth token (basic auth password)
  TRADEDOUBLER_TOKEN     Tradedoubler PRODUCTS site token
  TRADEDOUBLER_VOUCHER_TOKEN  Tradedoubler VOUCHERS site token
  WEBGAINS_TOKEN         Webgains personal access token (JWT; platform.webgains.io user settings)
  WEBGAINS_PUBLISHER_ID  Webgains publisher id (account info tab — NOT the affiliate/website id!)
  WEBGAINS_CAMPAIGN_ID   Webgains website/campaign id (websites & apps tab — this is wgcampaignid)
  SOVRN_API_KEY          Sovrn Commerce (ex-VigLink) secret key (platform.sovrn.com settings)

Requires: pip install requests
"""
import csv
import json
import os
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

try:  # Windows consoles may default to a legacy codepage
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = "affiliate-networks-toolkit/1.0 (+https://github.com/)"


# ---------------------------------------------------------------- helpers

def env(name, hint):
    v = os.environ.get(name)
    if not v:
        sys.exit(f"Set the environment variable {name} ({hint}).")
    return v


def flags_and_args(argv):
    fl, args = {}, []
    for a in argv:
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            fl[k] = v
        elif a.startswith("--"):
            fl[a[2:]] = True
        else:
            args.append(a)
    return fl, args


def get_json(url, headers=None, auth=None):
    r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})},
                     auth=auth, timeout=30)
    if not r.ok:
        sys.exit(f"HTTP {r.status_code} on {url.split('?')[0]}\n{r.text[:800]}")
    return r.json()


def emit(rows, fmt):
    rows = list(rows)
    if fmt == "csv":
        cols = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        w = csv.writer(sys.stdout, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
    else:
        print(json.dumps(rows, indent=2, ensure_ascii=False))


def xml_text(el, *names):
    """First non-empty text among several candidate child-element names (APIs are inconsistent)."""
    for n in names:
        c = el.find(n)
        if c is not None and c.text and c.text.strip():
            return c.text.strip()
    return ""


# ---------------------------------------------------------------- AWIN

def cmd_awin(sub, args, fl, fmt):
    if sub == "deeplink":
        # Built offline — no API call, no quota. awinmid = programme id from `programmes`.
        pub = env("AWIN_PUBLISHER_ID", "your AWIN publisher account id")
        if len(args) < 2:
            sys.exit("Usage: afftool.py awin deeplink <programme-id> <target-url>")
        mid, target = args[0], args[1]
        print(f"https://www.awin1.com/cread.php?awinmid={mid}&awinaffid={pub}&ued={quote(target, safe='')}")
        return

    token = env("AWIN_TOKEN", "AWIN personal access token")
    pub = env("AWIN_PUBLISHER_ID", "your AWIN publisher account id")
    rel = fl.get("relationship", "joined" if sub == "joined" else "notjoined")
    url = f"https://api.awin.com/publishers/{pub}/programmes?relationship={rel}&accessToken={token}"
    if fl.get("country"):
        url += f"&countryCode={fl['country']}"
    data = get_json(url)
    rows = []
    for p in data:
        # validDomains is an array of OBJECTS ({"domain": "*.example.com"}), not strings.
        domains = ";".join(d.get("domain", "") for d in (p.get("validDomains") or []))
        rows.append({
            "id": p.get("id"),                       # this is the awinmid for deeplinks
            "name": p.get("name"),                   # field is `name`, not `programmeName`
            "domains": domains,
            "status": p.get("status"),
            "displayUrl": p.get("displayUrl"),
            "primarySector": p.get("primarySector"),
            "currency": p.get("currencyCode"),
        })
    emit(rows, fmt)


# ---------------------------------------------------------------- CJ

CJ_ADV_FIELDS = {
    "id": ("advertiser-id",),
    "name": ("advertiser-name",),
    "programUrl": ("program-url",),
    "relationship": ("relationship-status", "account-status"),
    "sevenDayEpc": ("seven-day-epc",),
    "networkRank": ("network-rank",),
}


def cmd_cj(sub, args, fl, fmt):
    if sub == "deeplink":
        # /type/dlg/ takes the raw target URL appended to the path. It works even for
        # advertisers whose ready-made links report allow-deep-linking=false — that flag
        # describes the pre-built links, not the capability. Advertiser is inferred from
        # the target domain; you must be joined with them for the click to be credited.
        wid = env("CJ_WEBSITE_ID", "your CJ website id / PID")
        if not args:
            sys.exit("Usage: afftool.py cj deeplink <target-url>")
        target = args[0]
        if " " in target:
            sys.exit("Target URL contains spaces — encode it first.")
        print(f"https://www.anrdoezrs.net/links/{wid}/type/dlg/{target}")
        return

    token = env("CJ_TOKEN", "CJ personal access token")
    headers = {"Authorization": f"Bearer {token}"}

    if sub in ("joined", "programmes"):
        cid = env("CJ_CID", "your CJ company id (requestor-cid)")
        ids = "joined" if sub == "joined" else "notjoined"
        url = (f"https://advertiser-lookup.api.cj.com/v2/advertiser-lookup"
               f"?requestor-cid={cid}&advertiser-ids={ids}")
        if fl.get("query"):
            url += f"&keywords={quote(fl['query'])}"
        r = requests.get(url, headers={**headers, "User-Agent": UA}, timeout=30)
        if not r.ok:
            sys.exit(f"HTTP {r.status_code}\n{r.text[:800]}")
        root = ET.fromstring(r.content)
        rows = []
        for ad in root.iter("advertiser"):
            rows.append({k: xml_text(ad, *names) for k, names in CJ_ADV_FIELDS.items()})
        emit(rows, fmt)

    elif sub == "links":
        # NOTE: link-search takes website-id, NOT requestor-cid (sending requestor-cid is a 400).
        wid = env("CJ_WEBSITE_ID", "your CJ website id / PID")
        if not args:
            sys.exit("Usage: afftool.py cj links <advertiser-id>")
        url = (f"https://link-search.api.cj.com/v2/link-search"
               f"?website-id={wid}&advertiser-ids={args[0]}&records-per-page=100")
        r = requests.get(url, headers={**headers, "User-Agent": UA}, timeout=30)
        if not r.ok:
            sys.exit(f"HTTP {r.status_code}\n{r.text[:800]}")
        root = ET.fromstring(r.content)
        rows = []
        for link in root.iter("link"):
            rows.append({
                "linkId": xml_text(link, "link-id"),
                "name": xml_text(link, "link-name"),
                "type": xml_text(link, "link-type"),
                # ONLY clickUrl is your tracking link. `destination` is the landing page
                # and frequently contains someone ELSE'S tracking parameters. Never use it.
                "clickUrl": xml_text(link, "clickUrl", "click-url"),
                "allowDeepLinking": xml_text(link, "allow-deep-linking"),
            })
        emit(rows, fmt)
    else:
        sys.exit(f"Unknown cj subcommand: {sub}")


# ---------------------------------------------------------------- Impact

def cmd_impact(sub, args, fl, fmt):
    sid = env("IMPACT_ACCOUNT_SID", "Impact account SID")
    tok = env("IMPACT_AUTH_TOKEN", "Impact auth token")
    auth = (sid, tok)

    if sub in ("joined", "programmes"):
        # Impact's Campaigns endpoint returns ONLY joined programmes. There is no
        # discovery endpoint for brands you have not joined, and no join-via-API.
        data = get_json(f"https://api.impact.com/Mediapartners/{sid}/Campaigns?PageSize=100", auth=auth)
        rows = []
        for c in data.get("Campaigns", []):
            rows.append({
                "id": c.get("CampaignId"),
                "name": c.get("CampaignName"),
                "advertiser": c.get("AdvertiserName"),
                "advertiserUrl": c.get("AdvertiserUrl"),
                "contractStatus": c.get("ContractStatus"),
                "allowsDeeplinking": c.get("AllowsDeeplinking"),
                "deeplinkDomains": ";".join(c.get("DeeplinkDomains") or []),
            })
        emit(rows, fmt)

    elif sub == "deeplink":
        if len(args) < 2:
            sys.exit("Usage: afftool.py impact deeplink <program-id> <target-url>")
        program_id, target = args[0], args[1]
        r = requests.post(
            f"https://api.impact.com/Mediapartners/{sid}/Programs/{program_id}/TrackingLinks",
            auth=auth,
            headers={"Accept": "application/json", "User-Agent": UA},
            data={"DeepLink": target},
            timeout=30,
        )
        if not r.ok:
            sys.exit(f"HTTP {r.status_code}\n{r.text[:800]}")
        link = r.json().get("TrackingURL", "")
        print(link)
        print("\nWARNING: a clean API response does NOT mean this link works.", file=sys.stderr)
        print("Impact will happily generate tracking links for campaigns whose links are", file=sys.stderr)
        print("dead at click time ('Dead End' page) while reporting ContractStatus=Active.", file=sys.stderr)
        print("Open the link in a real browser (or: python linkcheck.py <link>) before shipping it.",
              file=sys.stderr)
    else:
        sys.exit(f"Unknown impact subcommand: {sub}")


# ---------------------------------------------------------------- Tradedoubler

def cmd_tradedoubler(sub, args, fl, fmt):
    # Site-level tokens only cover vouchers and product feeds. The full programme list
    # (joined advertisers + domains) sits behind the separate OAuth2 Publisher Management
    # API (connect.tradedoubler.com) and is intentionally NOT implemented here — see README.
    if sub == "vouchers":
        token = env("TRADEDOUBLER_VOUCHER_TOKEN", "Tradedoubler VOUCHERS site token")
        data = get_json(f"https://api.tradedoubler.com/1.0/vouchers.json?token={token}")
        items = data if isinstance(data, list) else data.get("vouchers", data.get("items", []))
        # Field structure varies; nominal programme-name fields have been observed empty.
        # We pass rows through as-is so nothing is silently dropped.
        emit(items, fmt)
    elif sub == "feeds":
        token = env("TRADEDOUBLER_TOKEN", "Tradedoubler PRODUCTS site token")
        data = get_json(f"https://api.tradedoubler.com/1.0/productFeeds.json?token={token}")
        items = data if isinstance(data, list) else data.get("productFeeds", data.get("items", []))
        emit(items, fmt)
    else:
        sys.exit("Tradedoubler subcommands: vouchers | feeds "
                 "(programmes/joined need the OAuth2 Publisher Management API — see README)")


# ---------------------------------------------------------------- Webgains

def cmd_webgains(sub, args, fl, fmt):
    if sub == "deeplink":
        # Built offline, no token needed. wgcampaignid = the WEBSITE/campaign id,
        # NOT the publisher id.
        camp = env("WEBGAINS_CAMPAIGN_ID", "Webgains website/campaign id (websites & apps tab)")
        if len(args) < 2:
            sys.exit("Usage: afftool.py webgains deeplink <programme-id> <target-url>")
        prog, target = args[0], args[1]
        print(f"https://track.webgains.com/click.html?wgcampaignid={camp}"
              f"&wgprogramid={prog}&wgtarget={quote(target, safe='')}")
        return

    token = env("WEBGAINS_TOKEN", "Webgains personal access token")
    headers = {"Authorization": f"Bearer {token}"}

    if sub == "programmes":
        # Full merchant directory — works with just the token, no publisher id needed.
        url = "https://platform-api.webgains.com/merchants/programs"
        if fl.get("name"):
            url += f"?filters[program_name]={quote(fl['name'])}"
        data = get_json(url, headers=headers)
        items = data.get("data", data if isinstance(data, list) else [])
        rows = []
        for p in items:
            rows.append({
                "id": p.get("id"),                    # this is the wgprogramid for deeplinks
                "name": p.get("name") or p.get("program_name"),
                "homepage": p.get("homepage_url") or p.get("homepage"),
                "status": p.get("status"),
                "allowsDeeplinks": p.get("allows_deeplinks"),
            })
        emit(rows, fmt)

    elif sub == "joined":
        # Needs the PUBLISHER id ("account information" tab), which is a DIFFERENT number
        # from the affiliate/website id ("websites & apps" tab). Using the wrong one is a 404.
        pub = env("WEBGAINS_PUBLISHER_ID", "Webgains publisher id (account info tab)")
        data = get_json(f"https://platform-api.webgains.com/publishers/{pub}/program_memberships",
                        headers=headers)
        items = data.get("data", data if isinstance(data, list) else [])
        rows = []
        for m in items:
            prog = m.get("program") or {}
            camp = m.get("campaign") or {}
            rows.append({
                "membershipId": m.get("id"),
                "programId": prog.get("id"),
                "programName": prog.get("name"),
                "campaignId": camp.get("id"),
                "statusCode": m.get("status"),  # numeric; meaning undocumented
            })
        emit(rows, fmt)

    else:
        sys.exit(f"Unknown webgains subcommand: {sub}")


# ---------------------------------------------------------------- Sovrn

def cmd_sovrn(sub, args, fl, fmt):
    key = env("SOVRN_API_KEY", "Sovrn Commerce secret key")
    if not args:
        sys.exit(f"Usage: afftool.py sovrn {sub} <url>")
    target = args[0]

    if sub == "wrap":
        print(f"https://redirect.viglink.com/?key={key}&u={quote(target, safe='')}")
    elif sub == "check":
        url = f"https://api.viglink.com/api/link/?out={quote(target, safe='')}&key={key}"
        if fl.get("geo"):
            url += f"&geo={fl['geo']}"
        data = get_json(url)
        emit([{
            "url": target,
            "affiliatable": data.get("affiliatable"),
            "optimized": data.get("optimized"),
            "eepc": data.get("eepc"),
        }], fmt)
    else:
        sys.exit(f"Unknown sovrn subcommand: {sub}")


# ---------------------------------------------------------------- main

NETWORKS = {
    "awin": cmd_awin,
    "cj": cmd_cj,
    "impact": cmd_impact,
    "tradedoubler": cmd_tradedoubler,
    "webgains": cmd_webgains,
    "sovrn": cmd_sovrn,
}


def main():
    fl, args = flags_and_args(sys.argv[1:])
    if len(args) < 2 or args[0] in ("help", "-h"):
        print(__doc__)
        return
    network, sub = args[0], args[1]
    fmt = fl.get("format", "json")
    if fmt not in ("json", "csv"):
        sys.exit("--format must be json or csv")
    fn = NETWORKS.get(network)
    if not fn:
        sys.exit(f"Unknown network: {network}. Choose from: {', '.join(NETWORKS)}")
    fn(sub, args[2:], fl, fmt)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Google data toolkit: Search Console, GA4 and Sheets through one service account.

Usage:
  python gtool.py token                        -> fetch an access token (smoke test)
  python gtool.py gsc-sites                    -> list the properties the SA can read
  python gtool.py gsc-query <property> [days]  -> top queries + pages (Search Analytics)
  python gtool.py gsc-inspect <property> <url> -> URL inspection (index status, canonical)
  python gtool.py ga4-report [property_id]     -> page views, last 7 days
  python gtool.py sheet-read <sheet_id> [range]
  python gtool.py sheet-write <sheet_id> <range> <value>

Configuration (environment variables):
  GOOGLE_SA_KEY      path to the service account JSON key   (required)
  GA4_PROPERTY_ID    default GA4 property for ga4-report    (optional)

Setup:
  1. Create a service account in Google Cloud and download its JSON key.
     Keep the key OUT of any synced folder (Dropbox/OneDrive/git).
  2. Enable the Search Console API, the Google Analytics Data API and the Sheets API.
  3. Grant access to the data, which is done per product, not in Cloud IAM:
     - Search Console: Settings > Users and permissions > add the SA e-mail (property owner must do this)
     - GA4: Admin > Property access management > add the SA e-mail as Viewer
     - Sheets: share the individual sheet with the SA e-mail
     Permissions only stick if the service account already exists - granting access
     to an SA address that has not been created yet silently does nothing.

Requires: pip install requests google-auth
"""
import json
import os
import sys
from datetime import date, timedelta

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

KEY_PATH = os.environ.get("GOOGLE_SA_KEY")
GA4_PROPERTY = os.environ.get("GA4_PROPERTY_ID")
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_session():
    if not KEY_PATH:
        sys.exit("Set GOOGLE_SA_KEY to the path of your service account JSON key.")
    if not os.path.exists(KEY_PATH):
        sys.exit(f"Key file not found: {KEY_PATH}")
    creds = service_account.Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
    creds.refresh(Request())
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {creds.token}"
    return s


def api(s, method, url, payload=None):
    r = s.request(method, url, json=payload)
    if not r.ok:
        print(f"HTTP {r.status_code} on {url}\n{r.text[:800]}")
        sys.exit(1)
    return r.json() if r.text else {}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "help":
        print(__doc__)
        return
    s = get_session()

    if cmd == "token":
        print("Token OK (service account authenticated)")

    elif cmd == "gsc-sites":
        data = api(s, "GET", "https://searchconsole.googleapis.com/webmasters/v3/sites")
        entries = data.get("siteEntry", [])
        if not entries:
            print("No properties shared - add the service account e-mail in Search Console.")
        for e in entries:
            print(f"{e['siteUrl']}  ({e['permissionLevel']})")

    elif cmd == "gsc-query":
        prop = sys.argv[2]
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 28
        end = date.today() - timedelta(days=2)  # Search Analytics lags ~2 days
        start = end - timedelta(days=days)
        payload = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["query", "page"],
            "rowLimit": 25,
        }
        url = (
            "https://searchconsole.googleapis.com/webmasters/v3/sites/"
            f"{requests.utils.quote(prop, safe='')}/searchAnalytics/query"
        )
        data = api(s, "POST", url, payload)
        for row in data.get("rows", []):
            q, page = row["keys"]
            print(
                f"{row['clicks']:>6.0f} clicks  {row['impressions']:>8.0f} impr.  "
                f"pos {row['position']:5.1f}  {q}  ->  {page}"
            )

    elif cmd == "gsc-inspect":
        prop, url_to_check = sys.argv[2], sys.argv[3]
        data = api(
            s,
            "POST",
            "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
            {"inspectionUrl": url_to_check, "siteUrl": prop},
        )
        res = data["inspectionResult"]["indexStatusResult"]
        print(f"Verdict: {res.get('verdict')}  Coverage: {res.get('coverageState')}")
        print(f"Google-selected canonical: {res.get('googleCanonical', '-')}")
        print(f"Last crawl: {res.get('lastCrawlTime', '-')}")

    elif cmd == "ga4-report":
        prop = sys.argv[2] if len(sys.argv) > 2 else GA4_PROPERTY
        if not prop:
            sys.exit("Pass a GA4 property id or set GA4_PROPERTY_ID.")
        payload = {
            "dateRanges": [{"startDate": "7daysAgo", "endDate": "yesterday"}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}],
            "orderBys": [{"desc": True, "metric": {"metricName": "screenPageViews"}}],
            "limit": 15,
        }
        data = api(
            s, "POST", f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport", payload
        )
        for row in data.get("rows", []):
            print(f"{row['metricValues'][0]['value']:>8}  {row['dimensionValues'][0]['value']}")

    elif cmd == "sheet-read":
        sheet_id = sys.argv[2]
        rng = sys.argv[3] if len(sys.argv) > 3 else "A1:E10"
        data = api(s, "GET", f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}")
        for row in data.get("values", []):
            print(" | ".join(row))
        if not data.get("values"):
            print("(range is empty)")

    elif cmd == "sheet-write":
        sheet_id, rng, value = sys.argv[2], sys.argv[3], sys.argv[4]
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}"
            "?valueInputOption=USER_ENTERED"
        )
        data = api(s, "PUT", url, {"values": [[value]]})
        print(f"Wrote {data.get('updatedCells', 0)} cell(s) to {data.get('updatedRange')}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()

# gsc-ga4-toolkit

One small CLI for the three Google surfaces an SEO or content agent actually needs: **Search Console**,
**GA4** and **Sheets** — all through a single service account, no browser, no OAuth dance, no scraping
of the Search Console UI.

The point is not the API calls, it is that an agent can now answer *"which queries does this URL
already rank for?"* with data instead of a guess.

## Quick start

```bash
pip install requests google-auth
export GOOGLE_SA_KEY=/path/to/service-account.json
export GA4_PROPERTY_ID=123456789            # optional

python gtool.py gsc-sites
python gtool.py gsc-query https://example.com/ 90
python gtool.py gsc-inspect https://example.com/ https://example.com/some-page/
python gtool.py ga4-report
```

## Setup, in the order that actually works

1. Create a service account in Google Cloud, download the JSON key. **Keep it out of synced folders
   and out of git.**
2. Enable the *Search Console API*, the *Google Analytics Data API* and the *Sheets API*.
3. Grant data access — this happens per product, not in Cloud IAM:
   - **Search Console:** Settings → Users and permissions → add the SA e-mail. Must be done by the
     property **owner**, not by any admin account.
   - **GA4:** Admin → Property access management → add the SA e-mail as Viewer.
   - **Sheets:** share the individual sheet with the SA e-mail.

🚨 Permissions only stick if the service account **already exists**. Granting access to an SA address
before creating it fails silently — you get a clean-looking grant and an empty property list.

## Things that cost us time

- **Search Analytics lags ~2 days.** Querying "today" or "yesterday" returns nothing. That is not an
  error, and `gsc-query` already shifts the window back by two days.
- **URL Inspection is part of the Search Console API** — there is no separate "Indexing API" for this.
  Quota is 2,000 calls/day.
- **Looker Studio has no data API.** If your numbers live there, go to the source behind it
  (BigQuery, GA4) instead of trying to extract the dashboard.
- **Google logged inflated impressions between 2025-05-13 and 2026-04-27** and did not correct the
  data retroactively. Impressions — and therefore CTR and average position — are unreliable in that
  window. **Clicks are unaffected.** If you compare before/after periods for a content change, either
  keep both windows outside that range or use clicks as the lead metric.

## Extending it

For anything the commands do not cover (filtering Search Analytics to a single page, other GA4
dimensions), copy the pattern in `gtool.py` and change the REST body — these are plain `requests`
POSTs against documented endpoints, not an SDK abstraction.

## License

MIT.

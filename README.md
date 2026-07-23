# SEO & Affiliate Toolkits

Small, battle-tested command-line tools for people who run content sites for a living.
Extracted from the daily editorial and monetisation work at [reisetopia](https://reisetopia.de),
generalised for any site. No frameworks, no services — Python scripts you can read in one sitting.

Each tool ships with the operational gotchas we learned the expensive way, documented in its README.

## The toolkits

### [`gsc-ga4-toolkit/`](gsc-ga4-toolkit/)
Google Search Console + GA4 + Google Sheets through **one service account**, as a CLI —
rankings, clicks/impressions per query and page, URL inspection, GA4 reports, sheet reads/writes.
No browser, no OAuth dance.

### [`dupe-audit/`](dupe-audit/)
Find near-duplicate paragraphs across a series of WordPress pages (shingle Jaccard with
entity/number masking). Catches the "same sentence, different brand" duplication that raw
text comparison misses.

### [`affiliate-networks-toolkit/`](affiliate-networks-toolkit/)
One CLI for AWIN, CJ, Impact, Tradedoubler, Webgains and Sovrn: programme discovery, joined
partnerships, offline deeplink building — plus a redirect-chain resolver that classifies link
inventories (working affiliate link / dead network / broken / soft-404), including target
recovery from dead zanox-era URLs.

## Requirements

Python 3.9+ and `requests`. Each toolkit documents its own credentials (environment variables
only — nothing is read from files) in its README.

## License

MIT — see [LICENSE](LICENSE).

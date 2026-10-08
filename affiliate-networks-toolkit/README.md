# affiliate-networks-toolkit

Two small scripts for anyone who runs affiliate links across several networks:

- **`afftool.py`** — one CLI for the publisher APIs of **AWIN, CJ, Impact, Tradedoubler,
  Webgains** and the **Sovrn Commerce** (ex-VigLink) wrapper: list programmes, check what you
  have joined, and build tracking deeplinks.
- **`linkcheck.py`** — a redirect-chain resolver that follows every hop of a link list and
  classifies each link: which network it runs through, whether it is broken, a soft-404, or
  quietly pointing at a network that no longer exists.

The point is not the API calls — those are documented. The point is the failure modes that are
*not* documented: links that return HTTP 200 and pay nobody, API fields that look like tracking
links but credit a stranger, and "Active" contracts whose links are dead. See
[Hard-earned gotchas](#hard-earned-gotchas).

## Quick start

```bash
pip install requests

export AWIN_TOKEN=...
export AWIN_PUBLISHER_ID=12345

python afftool.py awin joined
python afftool.py awin programmes --relationship=notjoined --country=DE --format=csv
python afftool.py awin deeplink 67890 "https://www.example.com/some-offer/"

# audit a link list
python linkcheck.py links.csv results.csv --own-domain=example.com

# inspect a single link's chain
python linkcheck.py "https://example.com/go/some-partner"
```

## Environment variables

Everything secret lives in environment variables. Nothing is read from config files, nothing is
ever written to disk.

| Variable | Network | What it is / where to get it |
|---|---|---|
| `AWIN_TOKEN` | AWIN | Personal access token: `ui.awin.com/awin-api` (needs the admin right on the account) |
| `AWIN_PUBLISHER_ID` | AWIN | Your publisher account id — the `awinaffid` in your existing links |
| `CJ_TOKEN` | CJ | Personal access token, self-service: developers.cj.com → Account → Personal Access Tokens |
| `CJ_CID` | CJ | Company id (`requestor-cid`), shown in the CJ account |
| `CJ_WEBSITE_ID` | CJ | Website id / PID. **Not exposed by any lookup API** — read it from the dashboard, or extract it from the `websiteId` field of a Commissions-API response |
| `IMPACT_ACCOUNT_SID` | Impact | Account SID (basic-auth username). Create an API token in the Impact dashboard with at least the Campaigns and Tracking Links scopes |
| `IMPACT_AUTH_TOKEN` | Impact | Auth token (basic-auth password) |
| `TRADEDOUBLER_TOKEN` | Tradedoubler | PRODUCTS **site** token (Settings → Tokens; Tradedoubler issues tokens per system + area, you cannot create them manually) |
| `TRADEDOUBLER_VOUCHER_TOKEN` | Tradedoubler | VOUCHERS **site** token |
| `WEBGAINS_TOKEN` | Webgains | Personal access token (JWT): platform.webgains.io → Account → User Management → your user → personal access token tab. Permissions hang on the **user**, not the token — the JWT's empty `scopes: []` field is misleading and not a blocker |
| `WEBGAINS_PUBLISHER_ID` | Webgains | Publisher id from the **account information** tab (see gotcha #4 — this is one of three different ids) |
| `WEBGAINS_CAMPAIGN_ID` | Webgains | Website/campaign id from the **websites & apps** tab (= `wgcampaignid` in links) |
| `SOVRN_API_KEY` | Sovrn | Secret key, self-service: platform.sovrn.com → Commerce → Settings |

Alternative names are accepted, so an existing setup does not need duplicate secrets:
`IMPACT_SID` for `IMPACT_ACCOUNT_SID`, `IMPACT_TOKEN` for `IMPACT_AUTH_TOKEN` and `SOVRN_KEY` for `SOVRN_API_KEY`.

## Commands

| Network | `programmes` (discovery) | `joined` | `deeplink` | extra |
|---|---|---|---|---|
| `awin` | ✅ full directory incl. not-joined (`--relationship=`, `--country=`) | ✅ | ✅ built offline, quota-free | |
| `cj` | ✅ advertiser search (`--query=`) | ✅ | ✅ `/type/dlg/` pattern, built offline | `links <advertiser-id>` — ready-made tracking links |
| `impact` | ❌ no discovery API (joined only) | ✅ | ⚠️ via API — **always live-test** (gotcha #3) | |
| `tradedoubler` | ❌ needs OAuth (see limitations) | ❌ | ❌ | `vouchers`, `feeds` |
| `webgains` | ✅ full directory (`--name=` filter) | ✅ | ✅ built offline | |
| `sovrn` | – | – | – | `wrap <url>`, `check <url>` — per-URL "is this monetisable?" |

List commands take `--format=json|csv` (default json).

```bash
python afftool.py webgains programmes --name=examplebrand
python afftool.py webgains deeplink 67890 "https://www.example.com/flights"
python afftool.py cj links 424242 --format=csv
python afftool.py cj deeplink "https://www.example.com/en-US/buy"
python afftool.py impact joined
python afftool.py sovrn check "https://www.example.com/product" --geo=de
```

## Hard-earned gotchas

Every one of these cost real time or real commission. They generalise beyond the specific
networks.

### 1. CJ Link Search: only `clickUrl` is your link — `destination` credits someone else

The Link Search API returns two URL fields per link. **`clickUrl`** is your tracking link
(`click-<yourPID>-<linkid>` on hosts like `tkqlhce.com`, `dpbolvw.net`, `anrdoezrs.net`,
`jdoqocy.com`, `kqzyfj.com`). **`destination`** is just the landing page — and in real
inventories it frequently contains *another network's tracking URL with a third party's
publisher id* baked in. For one advertiser we audited, two thirds of all `destination` fields
pointed at foreign tracking domains. Copy `destination` into your site and every sale pays a
stranger, while everything *looks* monetised. `afftool.py cj links` therefore emits `clickUrl`
and deliberately omits `destination`.

Corollary for audits: **judge the redirect chain, not the final URL.** A correct link and a
hijacked one can land on the identical final page; only the intermediate hops differ. That is
why `linkcheck.py` records every hop.

### 2. CJ deeplinks work via `/links/<PID>/type/dlg/<target-url>` — even when the API says no

The Link Search field `allow-deep-linking` describes the *pre-built links*, not the capability.
Appending any target URL to `https://www.anrdoezrs.net/links/<yourPID>/type/dlg/` produces a
working, tracked deeplink (final URL carries `cjevent=`/`cjdata=`) even for advertisers whose
inventory reports `allow-deep-linking=false` on nearly every link. If you only query
`link-search`, you will wrongly conclude that some target pages cannot be monetised.

### 3. Impact: "Active" contract ≠ working link — live-test every generated link

We hit an advertiser (the Points.com loyalty-programme storefronts) whose Impact campaigns
reported `ContractStatus: Active`, valid payouts, and `AllowsDeeplinking: true` — and whose
tracking links **all** landed on a "Dead End — the link you clicked on has expired" page. The
API happily generated fresh tracking links for them, domain-validated and error-free. The API
response status tells you nothing about whether the link works at click time.

**Rule: no generated link ships until it has been resolved in a real browser or via
`linkcheck.py`.** `afftool.py impact deeplink` prints a warning to stderr for exactly this
reason. (The same advertiser's links on CJ worked fine — when a brand is on several networks,
test which one actually resolves before choosing.)

### 4. Webgains uses three different ids, and picking the wrong one is a silent 404

- The **`aud` claim in the JWT** is the API's own generic client id (identical in the official
  docs' example token). It identifies nothing about your account. Ignore it.
- The **affiliate/website id** ("websites & apps" tab) is the `campaign` in REST paths *and*
  the `wgcampaignid` parameter in tracking links → `WEBGAINS_CAMPAIGN_ID`.
- The **publisher id** ("account information" tab) is the `{publisher}` in
  `/publishers/{publisher}/...` REST paths → `WEBGAINS_PUBLISHER_ID`.

Using the affiliate id in the publisher path position returns 404s that look like permission
problems. Meanwhile deeplink *construction* needs no REST call at all:
`track.webgains.com/click.html?wgcampaignid=<website-id>&wgprogramid=<programme-id>&wgtarget=<encoded-target>`.

### 5. Dead networks fail silently — and old zanox URLs still contain their target

When a network shuts down (zanox/Awin legacy hosts, ShareASale), its tracking domains stop
resolving, and every link pointing there becomes a dead click with zero commission — no error
in any dashboard, ever. `linkcheck.py` classifies these as `dead-network:<name>` instead of a
generic connection error.

Recovery: dead zanox URLs carry their original destination in the `ulp=` query parameter,
**double-percent-encoded**, sometimes with a nested Partnerize-style `destination:<encoded-url>`
sub-parameter inside. `linkcheck.py` peels both layers and reports the recovered merchant URL
in the notes column, so the link can be rebuilt on a living network instead of guessed at.

### 6. Always resolve the full chain — meta-networks hide in the middle hops

Sub-affiliate / auto-monetisation services (the digidip/Skimlinks/Sovrn class) sit *between*
your site and the merchant. A link that looks like a plain merchant URL in your CMS may hop
through one of them, and a link you believe runs through network A may be intercepted by
network B. Only the full hop list shows who is actually in the money path — which is why the
output has a `hops` column and the classifier matches *every* hop, not just the final host.

### 7. Soft-404s: HTTP says fine, the visitor is back on your homepage

Link-cloaking/shortener plugins commonly fall back to redirecting to your own homepage when
their target is missing. The chain is all clean 301s and a 200 — and the visitor never reaches
a merchant. Pass `--own-domain=yoursite.com` and `linkcheck.py` flags any chain that ends back
on your own domain as `soft-404`. In practice these are invisible in every status-code-based
monitor.

### 8. Host-based classification misses merchants that track via query parameters

Some partner programmes (common with travel/activity marketplaces) do not use a tracking
domain at all: the link goes straight to the merchant with a `partner_id=`-style query
parameter. A classifier that only looks at hostnames files these as "no affiliate" — we
mis-audited a fully-monetised set of links exactly this way. `linkcheck.py` therefore checks
the final URL for affiliate-looking parameters (`partner_id`, `clickid`, `irclickid`,
`cjevent`, `tduid`, `camref`, …) and reports `possible-params` before you write anything off.

### 9. Mind the rate limits

AWIN 20 req/min (feeds 5/min) · CJ Link Search 25/min · Webgains 60/min · Sovrn's bulk
merchant endpoint 1 request per 10 seconds. Directory listings barely change — cache them
nightly instead of querying live during an audit. Note that AWIN and Webgains deeplinks are
built offline from the programme id, so link building itself costs zero quota.

## Limitations (honest ones)

- **Tradedoubler `programmes`/`joined` is not implemented.** Site-level tokens only cover the
  Vouchers and Product-Feed APIs (both implemented). The full "my programmes" list requires
  the separate OAuth2 Publisher Management API (connect.tradedoubler.com) with its own client
  id/secret. Also: voucher objects have been observed with their nominal programme-name fields
  empty — inspect the raw JSON before building on a field.
- **Impact has no discovery endpoint.** `/Campaigns` returns joined programmes only; there is
  no API for browsing brands you have not joined, and no join-via-API. `impact programmes` is
  an alias for `joined` for interface symmetry.
- **CJ's website id is not exposed by any lookup API.** You need it from the dashboard, or by
  reading the `websiteId` field off a Commissions-API response. (If you go the GraphQL
  commissions route: date windows longer than ~30 days return HTTP 400 with an empty body.)
- **Webgains membership `status` is a bare numeric code** with no documented mapping and no
  matching field on the single-programme endpoint. It is passed through as-is.
- **The Impact vanity-domain list in `linkcheck.py` is not exhaustive** — Impact uses
  per-advertiser tracking domains. Extend `NETWORK_HOSTS` as you meet new ones.
- `impact deeplink` and `tradedoubler vouchers/feeds` response-field handling is best-effort
  against observed responses; both APIs have loosely documented schemas.

## License

MIT.

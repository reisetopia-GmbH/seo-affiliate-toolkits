# dupe-audit

Measure how much of a page series is the same text with the nouns swapped — and get a ranked list of
which paragraphs to fix first.

Built for the case where a content site has dozens of pages following one template ("credit cards in
Sweden", "credit cards in Denmark", …). They read fine individually. Collectively they are one page
repeated, and search engines treat them accordingly.

## Usage

```bash
pip install requests

# 1. pull the pages
printf 'guide-sweden\nguide-denmark\nguide-norway\n' > slugs.txt
python wp_fetch.py https://example.com slugs.txt pages.json --contains=/guides/

# 2. scan
python dupe_scan.py pages.json masks.json
```

Output: a per-page duplicate ratio on stdout and `dupe_clusters.json` with every cross-page cluster,
its member pages and a sample paragraph.

## The one thing that makes or breaks the result: masking

Before comparing, the scanner normalises away what is *supposed* to differ between sibling pages:

- every number → `#`
- the page's own entity terms → `entity`

`masks.json` is where you declare those terms per page:

```json
{
  "guide-sweden":  ["sweden", "swedish", "stockholm", "krona", "sek"],
  "guide-denmark": ["denmark", "danish", "copenhagen", "krone", "dkk"]
}
```

Slug words are masked automatically, so the config only needs the terms the slug does not contain —
adjectives, capital cities, currencies.

**Why it matters:** without masking, templated paragraphs score around 0.5 and the series looks
acceptable. With masking, the same paragraphs score above 0.9, because what is compared is the
sentence skeleton rather than the entity names. On a 65-page series this was the difference between
"looks fine" and *56 % of all paragraphs on the weak pages are duplicated* — which then dropped to
4 % after a rewrite driven by these clusters.

## Read the clusters before you delete anything

Two findings from doing this for real:

1. **Not every cluster is a defect.** Trust signals, editorial-standards blurbs and legal notes are
   *supposed* to be identical across pages. Decide per cluster; the tool ranks, it does not judge.
2. **Check for transclusion first.** On WordPress, the biggest cluster turned out to be a *reusable
   block* embedded on 63 pages — invisible in the page source as text, so a paragraph-level delete
   plan silently did nothing on every one of them. Before writing a fix script, scan the raw content
   for block references or shortcodes and handle those at the source.

## Tuning

| flag | default | meaning |
|---|---|---|
| `--min-chars` | 100 | ignore paragraphs shorter than this (nav, captions) |
| `--k` | 5 | shingle size in words; lower = more sensitive, noisier |
| `--dup` | 0.6 | score above which two paragraphs count as the same |

Pairs between 0.4 and the threshold are counted and reported but not clustered — useful for judging
whether your threshold sits in the right place.

## License

MIT.

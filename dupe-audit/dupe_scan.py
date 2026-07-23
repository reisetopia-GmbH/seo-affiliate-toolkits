# -*- coding: utf-8 -*-
"""Find near-duplicate paragraphs across a series of pages (shingle Jaccard).

Usage:
  python dupe_scan.py <pages.json> [masks.json] [--min-chars=100] [--k=5] [--dup=0.6]

<pages.json>  output of wp_fetch.py: {slug: {"html": …}}
[masks.json]  optional {slug: ["term", "term", …]} — see MASKING below

Writes dupe_clusters.json and prints a per-page duplicate ratio.

MASKING — the part that decides whether the result is meaningful
---------------------------------------------------------------
Two pages in a series usually differ only in the entity they are about ("prices in
Sweden" vs "prices in Denmark") and in their numbers. If you compare raw text, those
differences hide the duplication: templated paragraphs score ~0.5 and look acceptable.

So before comparing, this script normalises away exactly the things that are *supposed*
to differ:
  - all numbers      -> #
  - the page's own entity terms -> "entity" (from masks.json, plus the slug itself)

What is left is the sentence skeleton. A pair that still scores >0.6 is genuinely the
same paragraph with the nouns swapped — which is what a search engine sees too.

Without masking you will conclude the series is fine. With masking you find out it is not.
"""
import collections
import io
import itertools
import json
import re
import sys


def get_flag(name, default, cast=str):
    for a in sys.argv[1:]:
        if a.startswith(f"--{name}="):
            return cast(a.split("=", 1)[1])
    return default


def paragraphs(html, min_chars):
    out = []
    for p in re.findall(r"<p[^>]*>(.*?)</p>", html, re.S):
        t = re.sub(r"<[^>]+>", " ", p)
        for e, r in [
            ("&amp;", "&"), ("&nbsp;", " "), ("&ndash;", "–"), ("&mdash;", "—"),
            ("&#8211;", "–"), ("&quot;", '"'), ("&#039;", "'"),
            ("&auml;", "ä"), ("&ouml;", "ö"), ("&uuml;", "ü"), ("&szlig;", "ß"),
            ("&Auml;", "Ä"), ("&Ouml;", "Ö"), ("&Uuml;", "Ü"),
        ]:
            t = t.replace(e, r)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= min_chars:
            out.append(t)
    return out


def masks_for(slug, masks):
    """Entity terms to neutralise for this page: whatever the config lists, plus the slug words."""
    toks = set(masks.get(slug, []))
    base = re.sub(r"[-_]+", " ", slug).strip()
    toks.add(base)
    for w in base.split():
        if len(w) > 3:
            toks.add(w)
    return {t.lower() for t in toks if t}


def normalise(text, entity_terms):
    t = text.lower()
    for term in sorted(entity_terms, key=len, reverse=True):  # longest first, else partial hits
        t = t.replace(term, " entity ")
    t = re.sub(r"\d+(?:[.,]\d+)*", "#", t)
    t = re.sub(r"[^\w# ]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def shingles(t, k):
    w = t.split()
    return set(" ".join(w[i:i + k]) for i in range(len(w) - k + 1)) if len(w) >= k else {t}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter) if inter else 0.0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    # utf-8-sig, not utf-8: hand-written config files on Windows often carry a BOM,
    # which json.load rejects with a message nobody enjoys debugging.
    pages = json.load(open(args[0], encoding="utf-8-sig"))
    masks = json.load(open(args[1], encoding="utf-8-sig")) if len(args) > 1 else {}

    min_chars = get_flag("min-chars", 100, int)
    k = get_flag("k", 5, int)
    dup_at = get_flag("dup", 0.6, float)
    near_at = 0.4

    allp = []  # (slug, index, text, shingle set)
    for slug, d in pages.items():
        terms = masks_for(slug, masks)
        for i, t in enumerate(paragraphs(d["html"], min_chars)):
            allp.append((slug, i, t, shingles(normalise(t, terms), k)))
    print(f"Pages: {len(pages)} | paragraphs >={min_chars} chars: {len(allp)}")

    # Union-find over paragraphs that are duplicates of each other
    parent = list(range(len(allp)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Inverted index over sampled shingles keeps this from being O(n^2) on real corpora
    inv = collections.defaultdict(list)
    for idx, (_, _, _, sh) in enumerate(allp):
        for s in itertools.islice(sh, 40):
            inv[s].append(idx)
    cand = collections.defaultdict(set)
    for s, ids in inv.items():
        if len(ids) < 2 or len(ids) > 80:  # ultra-common shingles carry no signal
            continue
        for a, b in itertools.combinations(ids, 2):
            if allp[a][0] != allp[b][0]:  # only ACROSS pages
                cand[a].add(b)

    pair_scores = {}
    for a, bs in cand.items():
        for b in bs:
            key = (min(a, b), max(a, b))
            if key in pair_scores:
                continue
            score = jaccard(allp[a][3], allp[b][3])
            if score >= near_at:
                pair_scores[key] = score
                if score > dup_at:
                    union(a, b)
    print(
        f"Paragraph pairs >={near_at}: {len(pair_scores)} | "
        f"of those >{dup_at} (clear duplicate): {sum(1 for v in pair_scores.values() if v > dup_at)}"
    )

    clusters = collections.defaultdict(list)
    for idx in range(len(allp)):
        clusters[find(idx)].append(idx)
    clusters = {
        kk: v for kk, v in clusters.items()
        if len(v) >= 2 and len(set(allp[i][0] for i in v)) >= 2
    }

    result = []
    for v in sorted(clusters.values(), key=lambda v: -len(set(allp[i][0] for i in v))):
        hit = sorted(set(allp[i][0] for i in v))
        result.append({"pages": len(hit), "paragraphs": len(v), "slugs": hit, "sample": allp[v[0]][2][:400]})
    json.dump(result, open("dupe_clusters.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    dup_par = set(i for v in clusters.values() for i in v)
    per_page = collections.defaultdict(lambda: [0, 0])
    for idx, (slug, _, _, _) in enumerate(allp):
        per_page[slug][1] += 1
        if idx in dup_par:
            per_page[slug][0] += 1

    print(f"\nCross-page clusters (>{dup_at}): {len(result)}")
    print("\n=== TOP 15 CLUSTERS (by pages affected) ===")
    for c in result[:15]:
        shown = ", ".join(c["slugs"][:12]) + (" …" if len(c["slugs"]) > 12 else "")
        print(f"\n• {c['pages']} pages / {c['paragraphs']} paragraphs: {shown}")
        print(f"  » {c['sample'][:250]}")
    print("\n=== DUPLICATE RATIO PER PAGE (top 20) ===")
    for slug, (d, t) in sorted(per_page.items(), key=lambda kv: -(kv[1][0] / max(1, kv[1][1])))[:20]:
        print(f"  {d:>3}/{t:<3} ({100 * d / max(1, t):4.0f} %)  {slug}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()

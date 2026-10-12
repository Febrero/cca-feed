"""Google Merchant Center feed for caramulocom.art (C C A · Caramulo com Arte), built from the shop's own
public pages, because SITE123 locks its feed behind a higher plan.

Reads every product page listed in the shop's sitemaps, keeps only what is for sale (SITE123 marks a sold
item by setting its price to 0) and writes feed.xml (RSS 2.0 + g: namespace) for a scheduled fetch in
Merchant Center. Standard library only, so it runs the same locally and on GitHub Actions.
  python build_feed.py [out.xml]
"""
import concurrent.futures as cf
import html
import json
import re
import sys
import time
import urllib.request
from xml.sax.saxutils import escape

try:  # on Pedro's PC Avast re-signs TLS; the Windows store trusts its root
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

SITE = "https://www.caramulocom.art"
UA = {"User-Agent": "Mozilla/5.0 (compatible; CCA-feed/1.0; +https://www.caramulocom.art)"}
SMALL = {"a", "o", "as", "os", "e", "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos", "por",
         "para", "com", "um", "uma", "ao", "à", "aos", "às", "the", "of", "and", "la", "le", "les", "el", "y", "du", "des"}


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                return None
            time.sleep(2 * (i + 1))


def product_urls():
    index = get(f"{SITE}/sitemap.xml") or ""
    maps = [u for u in re.findall(r"<loc>([^<]+)</loc>", index) if "ecommerce" in u]
    urls = []
    for m in maps:
        urls += re.findall(r"<loc>([^<]+)</loc>", get(m) or "")
    return list(dict.fromkeys(html.unescape(u) for u in urls))


def nice_title(name):
    """'Bessa-Luís, Agustina, CONTOS IMPOPULARES' -> 'Bessa-Luís, Agustina, Contos Impopulares':
    Merchant Center flags titles in capitals; only all-caps words are recased."""
    words = name.split(" ")
    out = []
    for i, w in enumerate(words):
        letters = [c for c in w if c.isalpha()]
        if len(letters) > 1 and all(c.isupper() for c in letters):
            lw = w.lower()
            w = lw if (i and lw.strip(",.;:") in SMALL) else lw[:1].upper() + lw[1:]
            if re.fullmatch(r"[ivxlcdm]+[.,]?", lw):  # roman numerals stay in capitals
                w = w.upper()
        out.append(w)
    return " ".join(out)


def parse(url):
    page = get(url)
    if not page:
        return {"failed": url}
    prod = None
    for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            prod = data
    if not prod:
        return None
    offer = prod.get("offers") or {}
    try:
        price = float(offer.get("price") or 0)
    except ValueError:
        price = 0
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', page)
    og_img = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    sku = (prod.get("sku") or "").strip()
    is_art = not sku.lower().startswith("l-")  # books are coded l-…, art objects p-/o-/…
    return {
        "id": sku or re.sub(r"\W+", "-", url.rsplit("/", 1)[-1])[:50],
        "title": nice_title(re.sub(r"\s+", " ", html.unescape(prod.get("name", ""))).strip())[:150],
        "description": re.sub(r"\s*\n\s*", " · ", html.unescape(prod.get("description", "")).strip())[:5000],
        "link": html.unescape(canon.group(1)) if canon else url.split("?")[0],
        "image": html.unescape(og_img.group(1)) if og_img else (prod.get("image") or [""])[0],
        "price": price,
        "in_stock": "InStock" in (offer.get("availability") or ""),
        "kind": "Arte" if is_art else "Livros",
    }


def item_xml(p):
    rows = [
        ("g:id", p["id"]), ("g:title", p["title"]), ("g:description", p["description"] or p["title"]),
        ("g:link", p["link"]), ("g:image_link", p["image"]), ("g:availability", "in_stock"),
        ("g:price", f"{p['price']:.2f} EUR"), ("g:condition", "used"), ("g:identifier_exists", "no"),
        ("g:product_type", p["kind"]),
    ]
    if p["kind"] == "Livros":
        rows.append(("g:google_product_category", "784"))  # Media > Books
    return "  <item>\n" + "".join(f"    <{k}>{escape(str(v))}</{k}>\n" for k, v in rows) + "  </item>\n"


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "feed.xml"
    urls = product_urls()
    with cf.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(parse, urls))
    # SITE123 times out under parallel load: retry the pages that did not answer, slowly
    for attempt in range(2):
        failed = [r["failed"] for r in res if r and "failed" in r]
        if not failed:
            break
        print(f"retry {attempt + 1}: {len(failed)} pages did not answer", flush=True)
        res = [r for r in res if not (r and "failed" in r)]
        with cf.ThreadPoolExecutor(2) as ex:
            res += list(ex.map(parse, failed))
    unread = sum(1 for r in res if r and "failed" in r)
    found = [r for r in res if r and "failed" not in r]
    seen, items = set(), []
    for p in found:
        if p["price"] <= 0 or not p["in_stock"] or not p["image"] or p["id"] in seen:
            continue  # sold (price 0), out of stock, no photo, or the same product under another URL
        seen.add(p["id"])
        items.append(p)
    with open(out, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">\n'
                f"<channel>\n  <title>C C A · Caramulo com Arte</title>\n  <link>{SITE}</link>\n"
                "  <description>Livros antigos e usados e objetos de arte</description>\n")
        f.writelines(item_xml(p) for p in items)
        f.write("</channel>\n</rss>\n")
    kinds = {k: sum(1 for p in items if p["kind"] == k) for k in ("Livros", "Arte")}
    print(f"{len(urls)} URLs, {len(found)} product pages read ({unread} never answered), {len(items)} for sale "
          f"in the feed {kinds}, {sum(1 for p in found if p['price'] <= 0)} sold (price 0) left out -> {out}")
    if unread > len(urls) * 0.2:
        sys.exit("too many pages did not answer: feed written but incomplete")


if __name__ == "__main__":
    main()

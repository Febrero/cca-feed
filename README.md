# C C A · Caramulo com Arte — Google Merchant feed

`feed.xml` lists the books and art objects for sale on https://www.caramulocom.art, built from the shop's
public pages by `build_feed.py` (sold items, which SITE123 shows at 0 €, are left out). A GitHub Action
rebuilds it twice a week. Google Merchant Center fetches it from:

https://febrero.github.io/cca-feed/feed.xml

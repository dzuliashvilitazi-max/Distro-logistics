# Smart Pricing

## Recommendation Endpoint

`POST /api/store/pricing/advisor` is available to retailer users with `canChangePrices`. It accepts a delivered order and product, plus an optional planned price. The response provides the cost, backend-calculated profit/margin, recommended price, market medians, sample sizes, and recommendation basis.

The recommendation uses:

1. A target gross-margin floor of 25%: `unit_cost / (1 - 0.25)`.
2. An internal benchmark from POS sales belonging to at least three other retailers. Each retailer first contributes its own median, so high-volume stores do not dominate the result.
3. An external benchmark from at least three distinct approved sources. Only GEL observations from the last 30 days with confidence of at least 0.80 are considered; each source contributes its own median.
4. If both market medians exist, a weighted reference of 70% internal POS and 30% external market prices. The competitive target is 2% below that reference, but the recommendation never falls below the margin floor.
5. If only one source has enough observations, that source is used as the reference. If neither source qualifies, the endpoint falls back to the margin floor.

This is a transparent market-and-margin heuristic, not a guaranteed profit optimum. True profit maximization requires demand elasticity, stock, price history and conversion data to estimate how sales volume changes with price.

All price arithmetic is performed with Python `Decimal` and serialized only at the API boundary.

## External Market Data

`POST /api/admin/pricing/benchmarks` accepts up to 500 observations per request and is admin-only. Each observation must map to an existing product and contain a source label, HTTPS product URL, positive GEL price, confidence from 0 to 1, and timezone-aware observation time. Observations are deduplicated by a fingerprint and stored with Decimal128 prices. Benchmarks older than 30 days or below the confidence threshold are excluded from recommendations.

The application does not scrape websites or social networks. Connect a licensed marketplace/social listening provider or an approved catalog feed to this admin endpoint. The adapter must verify the provider's source and product match, normalize prices to GEL, assign a defensible confidence score, and preserve the original HTTPS URL and observation time. Do not ingest prices from private or access-controlled pages without authorization.

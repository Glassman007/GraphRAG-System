# External API Pagination

Collection endpoints use bounded cursor pagination.

Typical parameters:

```text
limit=50
cursor=<opaque cursor>
```

Responses expose `items`, `next_cursor`, and `has_more` where pagination applies. Cursors encode stable external IDs rather than database offsets and are validated before use. Invalid cursors fail instead of silently restarting at page one.

The external maximum page size is 100. Other expensive operations have independent hard bounds, including graph path hops, blast-radius depth, retrieval result count, and graph-neighbor limits.

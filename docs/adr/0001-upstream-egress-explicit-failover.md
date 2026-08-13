# Upstream egress is explicit, with failure-only failover

Status: accepted

The vision proxy's upstream requests used `urllib`'s default opener, which on Windows silently follows the system proxy; when the user's Clash (127.0.0.1:7890) was down, every upstream request was refused and the whole 19100 chain returned 502. We replaced the implicit opener with an explicit egress layer: requests go direct (TCP+TLS) by default, or through an optional `--upstream-proxy` CONNECT tunnel (`VISION_UPSTREAM_PROXY` env fallback, `--proxy-first` to reorder), and the system proxy is never consulted.

Routing is sticky in memory: the route whose connection (TCP/TLS, bounded at 5s) succeeds is reused for subsequent requests, and switching happens only when that route fails to establish a connection — HTTP-layer errors pass through unchanged, there is no periodic re-probing, and when every route fails the client gets a 502 listing each route and reason. Connection timeouts are short (5s per candidate) so failover is fast, while streaming after connection keeps the long 600s read timeout.

Considered Options:

- **Keep following the system proxy** — rejected: it makes the proxy's behavior depend on a machine-wide setting that can change out from under it, and a dead local proxy takes the entire chain down.
- **Bypass the system proxy entirely (`ProxyHandler({})`)** — rejected: it silently drops users who genuinely need a proxy, with no way to opt back in.
- **Adaptive routing with periodic health checks** — rejected: over-engineered for a local relay; the user wants the simplest failure-only switch, reset on process restart.

Consequences:

- Default installs go direct, so a Clash outage no longer breaks the chain.
- Users behind a required proxy must configure `--upstream-proxy` / `VISION_UPSTREAM_PROXY` explicitly.
- Sticky state is in-memory only; restarting the proxy returns to the default order.

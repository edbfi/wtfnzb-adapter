# Project status and remaining work

The September 20 prototype implements the [evidence-based scope](implementation-scope.md).
Both movie and TV backlog remain required. This is an experimental integration,
not a claim that unreliable upstream historical search has been repaired.

## Delivered

- uv initialization, Python 3.14, Litestar/GranianPlugin, msgspec, locked dependencies.
- Newznab capability/result translation, RSS categories/sizes/dates, TV catalogue
  lookup, strict archive completion validation, bounded detail enrichment and NZB retrieval.
- Serialized upstream access, persistent budgets/cooldowns, bounded caches and reads,
  singleton state lock, explicit unsupported/authentication/upstream errors.
- Optional protected Ego session capture and guarded experimental renewal flow.
- Structural basedpyright policy checker, temporary-project negative tests,
  project-wide prek gates, both hook stages, CI tests/builds and Conventional Commits.
- Sanitized fixtures and live validation records; no download jobs or forum posts.

## Remaining reliability gates

1. Resolve upstream archive incompleteness, inconsistent result counts and broken
   no-result behavior. Movie/title-only broadening is not a complete substitute:
   the sampled first 100 Casablanca results contained only seven 1942-film matches.
   The [upstream report](upstream-report.md) is prepared but has not been sent.
2. Verify fresh-session acquisition and expiry renewal on the eventual deployment
   host. A corrected browser login and existing-session export worked; challenges,
   IP binding, expiry and headless deployment remain uncertain.
3. Establish networking between the deployment host and the user's Prowlarr. The
   local adapter must be reachable from that host, and the host must reach WTFNZB.
4. Increase useful movie coverage without causing one detail request per hundreds
   of candidates. The current five-candidate enrichment window can omit matching
   categories and is deliberately documented rather than concealed.
5. Validate more TV catalogue titles, aliases, ambiguous series and oversized pages.
   Known complete pages do not establish that every show has a complete history.
6. Confirm historical date timezone and real Usenet article availability. Displayed
   sizes are rounded; anomalous NZB segment zero is preserved as upstream data.

Do not advertise identifier lookup, arbitrary archive pagination, automatic RSS
history collection, category guesses, or unattended session reliability. Do not
silently turn partial searches into empty success to make Prowlarr validation pass.

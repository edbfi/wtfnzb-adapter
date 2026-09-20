# First implementation scope

This is a limited, experimental Newznab adapter, not a claim of complete or
reliable access to WTFNZB's entire archive. Both TV and movie support remain
requirements. The user authorized continuing autonomously and delivering as much
working integration as the evidence supports.

## Decisions following discovery

- Expose Newznab caps, RSS/search XML and controlled NZB retrieval through
  Litestar. Advertise text search and the implemented TV season/episode fields;
  do not advertise unverified identifier search.
- Empty search uses the current RSS window. Preserve exact feed sizes, explicit
  date offsets and item-scoped category links. Map category IDs by meaning.
- TV searches may resolve a show through `/series?title=...` and fetch its
  complete series page. Reject oversized or incomplete pages. Match titles
  conservatively, deduplicate GUIDs and filter actual release metadata locally.
- General/movie text queries use the archive POST. Accept only responses with
  a verified finished marker and consistent count. Timeouts, partial streams and
  ambiguous empty results become explicit upstream errors, never empty success.
  The stale `/api_fast` corpus is not a silent fallback.
- Bound the archive candidate window before enrichment and document the cap.
  Recover real category and rounded size from detail pages for this window;
  filter and paginate the resulting bounded snapshot. No title-based category
  guesses and no implied pagination over the whole upstream archive.
- Clearly identify converted detail/series sizes as approximate. Archive dates
  require a configured timezone because their source has no offset; RSS dates
  retain the supplied offset. No claimed verification of the site's winter
  timezone follows from the observed summer `+0200` feeds.
- Keep one upstream request in flight, with global spacing and hourly/daily
  budgets covering all upstream operations. Cache bounded results and metadata,
  deduplicate concurrent work, honor cooldowns and fail explicitly when budgets
  or caller deadlines are exhausted. No archive crawl or automatic query retry.
- Start with memory caches and small protected local session/limiter state.
  A relational database, background collector and deployment replicas are not
  needed for this scope.
- Load runtime secrets from environment/secret files. Provide an optional local
  Ego Lite session helper: reuse its authorized browser session, extract API/RSS
  credentials privately, and use the verified login form only when needed.
  Browser challenges needing human action and rejected logins stop refresh.
  Unattended operation on another deployment host remains unverified.
- Forward NZBs only after checking the bounded response is NZB XML, preserving
  upstream content. The observed zero-number segment remains an upstream caveat;
  do not silently rewrite it or claim article availability.

## Acceptance gates

Test parsing and failures against sanitized real responses, including the
67/four-result contradiction. Test rate limits, cache bounds, authentication
latching and credential redaction without live services. Enforce the requested
typing policy in both CI and prek, with no global diagnostic overrides.

Validate caps, RSS, actual searches, metadata, category filtering and retrieval
through the running Prowlarr where connectivity permits. Record incomplete or
blocked checks. The prototype is useful only within these explicit limits;
passing Add Indexer is not completion of the full integration goal.

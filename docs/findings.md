# WTFNZB investigation — 2026-09-19

## Decision and current status

September 20 local-time update: **both TV and movie backlog search are required**.
The [movie follow-up](movie-and-login-follow-up.md) found historical releases
dating to 2019 and working detail/NZB retrieval, but identical searches returned
67 and four results. Login testing encountered an explicit IP ban after an
unquoted password was truncated by `.env` parsing; the configuration was fixed
locally and requests stopped. After the user restored access, corrected browser
login and independent PHP-session reuse succeeded. Fresh-session acquisition
and unattended renewal remain unverified.

**Outcome: general historical integration has an unmet reliability gate; a
separate TV catalogue is a promising alternative.** See the
[deeper endpoint trace](deeper-api-trace.md): complete series pages returned
1,168 and 63 releases, with metadata and dates reaching back to 2022. This is a
finding about tested behavior, not proof that no future adapter can work. The
user wants automatic session renewal and low upstream load, provided the service
works reliably. Current evidence does not satisfy full reliability. A bounded
experimental adapter has now been initialized and implemented; see
[validation](validation.md) and [implementation scope](implementation-scope.md).
Successful prototype checks do not establish comprehensive archive support.

Direct Generic Newznab integration does not work. Recent RSS adaptation is
feasible, but **RSS-only is not the selected product scope**: the user needs
search beyond that window. Investigation now also covers the reworked archive
search and session-authenticated metadata recovery. Full historical integration
is not yet established.

The API's searchable data was stale during this investigation. Its missing
metadata cannot be recovered using the tested API credentials on detail pages,
but an independent HTTP client using the existing PHP session can recover it.
Search completeness and session lifecycle remain constraints. Do not make Add
Indexer pass by inventing sizes or classifying titles.

## Baseline and evidence

Investigation: 2026-09-19, starting approximately 20:58 UTC. Browser: existing
authorized Ego Lite session, separate task space. Independent client: Node fetch,
no cookies, normal certificate verification. Requests were sequential; after
early intermittent failures, probes were spaced approximately 1.5 seconds apart.
Raw private material is outside the checkout; repository fixtures replace the
private origin and credential values. No cart-removal URLs were requested.

[probes.json](evidence/probes.json) records request parameters, authentication
parameter names, timestamp, client, status, content type, redirects, size, and
original-response hash. Hashes describe private originals, not sanitized files.
Credential values are deliberately indistinguishable placeholders; use the
variant descriptions below when reproducing authentication tests. The accidental
`q=undefined` caps probe was discarded and repeated correctly.

The running Prowlarr status page reports **2.6.5.5623**, Hotio package
`release-40779f2`, .NET 8.0.27. The local source's `develop` HEAD and tag
`v2.6.5.5623` both resolve to
`12c327808314a7cae1b7301935ee10cabc19609f`.
Indexer definitions: `master`,
`b6af805b1441881354cb3f7422a7d6f2602efe24`. No WTFNZB definition was found there.
These repositories were inspected without modifications.

## Capability matrix

| Feature | Classification | Observed evidence / limitation |
| --- | --- | --- |
| Newznab capabilities | Unsupported directly | `/api?t=caps&apikey=…` redirects 302 to `/api_fast`, losing the entire query; final 200 HTML says query must exceed two letters. `/api_fast?t=caps` also returns that HTML. |
| API text search | Working directly, limited | `q=linux` produces 22 RSS items without cookies; browser and independent client returned identical bodies. Results have titles, GUIDs, download links and naive dates, no sizes or categories. |
| API freshness | Not reliable | `q=SpongeBob` gives 18 July/August items while RSS has September releases. A non-ASCII query unexpectedly exposed all 100,000 API items, dated July 31–August 7. Do not reproduce this unbounded request. |
| Empty/short query | Unsupported directly | `q=` and `q=ab`: 200 HTML, not empty RSS. |
| Legitimate no results | Working directly | `q=wtfnzbadapternomatch20260919`: valid RSS, zero items and response total 0. |
| Punctuation | Working in one sample | `q=linux.x64`: six matching-looking items. General tokenizer semantics remain unverified. |
| Non-ASCII API search | Broken in one sample | `q=修仙传`: 100,000 items / 96,577,276 bytes, only three titles containing that text. HTTP success is not search success. |
| API limit/offset/category | Unsupported in sample | `limit=1`, `offset=1`, and `cat=2000`, individually added to Linux baseline, returned byte-identical 22-item bodies. |
| API ordering | Unverified | Probe combining `order=title&sort=asc` got 403; it does not isolate ordering behavior. |
| TV/identifier search | Unsupported in samples | `t=tvsearch&q=SpongeBob&season=99` is identical to ordinary SpongeBob search; `t=movie&imdbid=0133093` without q returns short-query HTML. All possible identifier modes were not exhausted. |
| Archive UI | Conditional adaptation, incomplete reliability | `/_search_` embeds `/_search_.php/_search_`; a session-authenticated multipart POST can return historical results. Cookie-free GET got 403. See follow-up for truncated streams and timeouts. |
| TV catalogue | Candidate adaptation | `/series?title=…` resolves internal show IDs; two complete series pages supplied historical titles, GUIDs, categories, dates and rounded sizes in bulk. No proof of exhaustive coverage, general search or stable size bounds. |
| Recent RSS | Working directly | `/rss?t=0&dl=1&i=…&r=…`: 50 current items without cookies. New items appeared between probes. No completeness guarantee. |
| RSS category filters | Working in samples | Parent 2000/4000/5000, subcategory 5045, and combined 2000,4000 all produced category-consistent item descriptions. |
| RSS count/pagination | Unsupported in samples | `num=1`, `num=5`, `num=100` each return 50. TV `num=1` and `num=100` have identical GUID sets; `offset=50` also returns that set. |
| RSS sizes/dates/categories | Feasible with adaptation | Exact size attribute/enclosure length; dated `usenetdate`; blank pubDate and category attributes; numeric category in the description's item metadata. |
| Historical metadata recovery | Feasible with PHP session; blocked with tested API-only auth | Detail URL alone, API credentials, and RSS credentials redirect to login. PHPSESSID alone works for independent detail reads. TV series pages also provide bulk metadata; durable session handling remains unverified. |
| NZB retrieval | Working directly in controlled samples | Recent RSS credential links and one March 2022 release using PHPSESSID returned 200 application/x-nzb with NZB XML. Segment-number caveat remains. |
| Account/rate limits | Unverified | Profile shows VIP role and usage counters but no numeric quota in inspected text. One initial 503 and a cluster of 403 responses recovered on later probes. No load test or rate-limit exhaustion. |

## Authentication and error semantics

API help labels both `apikey` and `r` as the API key and `i` as user ID.
Its example uses base64(decimal user ID) for `i`. RSS examples use decimal `i`.
The account's `apikey` and `r` values are equal.

The documented API example works without cookies. Rechecking decimal API `i`
also returned results, but generated link bytes differed; merely accepting the
search does not prove its generated download authentication is correct. Omitting
`r` still returned search results with shorter links. A deliberately invalid
`apikey` returned **200 with a zero-byte HTML body**, not a Newznab error or an
empty-result feed. Initial missing-key and other auth variants got intermittent
403 responses, so credential necessity beyond these observations is unresolved.

RSS with correct decimal `i` and `r` works without cookies. Missing or invalid
RSS credentials redirect to `/login`, which returns Cloudflare challenge HTML
403. This establishes the login redirect; it does not establish that every 403
means bad credentials. Avoid following login/challenge redirects in a service.
Separate transport failures, denied credentials, malformed payloads, unsupported
queries, and a valid zero-item RSS response.

Later session-route probes temporarily used the existing PHP session in a
private local HTTP client. No cookie was placed in the repository or configured
in a deployed service. The private hostname itself is configuration and must
not appear in shared fixtures or logs.

## Follow-up: reworked archive search

The user pointed to `/forumpost/4699`. The inspected September 8 administrator
replies say API/RSS should work again and search was reworked. They do **not**
confirm that the API contains the newest 100,000 releases or provide a new API
protocol. `/search` resolves to `/_search_`; the wrapper displays a September 8
re-index timestamp and embeds `/_search_.php/_search_`.

The actual search operation is **POST**, not the form's nominal GET method.
Inline JavaScript prevents normal submission and sends multipart fields
`do_search=1`, `csrf=<page token>`, `search=<query>`, and `results=100` or `1000`
to the iframe URL. It uses the current session and streams HTML result fragments.
Do not reproduce the earlier GET comparison as though it executes a search.

An independent client can GET the search page using **PHPSESSID alone**; the
Cloudflare clearance cookie was unnecessary in that successful probe. A
cookie-free client gets 403. Cookie authentication has only been verified from
this workstation, not a deployment host. PHPSESSID is a browser-session cookie;
the site's server-side expiry and renewal requirements remain unknown.

Observed session searches:

- `linux`, results=100: 100 results in under one second and a
  `<div class="finished">` marker. Dates extend back to July 19. The last
  timestamp is not necessarily the oldest site release; the response hit its cap.
- `SpongeBob.SquarePants.S01E19`: the browser eventually displayed nine results,
  extending to March 2024. A cookie-bearing independent POST returned four
  results then ended at the HTTP layer after about five seconds, **without the
  finished marker**. A retry yielded nine results but was still incomplete at
  the client-imposed 25-second bound. HTTP 200 and EOF are insufficient proof
  of a complete search. Results were not strictly descending by date.
- `Outlander.Blood.of.My.Blood.S02E01`, known to occur in current RSS: one
  search-page bootstrap failed, and a retry timed out at 25 seconds. Neither
  is a legitimate no-result observation.
- `/api_fast?q=SpongeBob.SquarePants.S01E19` returned a valid empty feed,
  although the current RSS contained a matching release. Adding one cache-busting
  parameter did not change it. This reinforces the freshness concern.
- `/searchraw?search=SpongeBob.SquarePants.S01E19` in the browser reported no
  matching raw headers; raw-header search is not established as a release API.

A final attempt with a 90-second allowance failed before searching: GET of the
CSRF/bootstrap page returned HTTP 502. Increasing the search timeout alone does
not resolve that failure.

After the user conditionally accepted session renewal, a further **isolated**
90-second probe returned nine results and closed after 47.952 seconds, again
without the finished marker. The client did not abort this response. This
separates that outcome from the earlier 25-second client limit. It does not prove
the precise backend termination cause or that a marker is guaranteed at natural
EOF; the different four/nine-result outcomes and absence of a stated completion
contract are the reliability concern. No load test was performed.

The final no-match control (`wtfnzbadapternomatch20260919`) returned HTTP 200
after 10.572 seconds with zero results and a `class="timeout-error"` block
saying no result was found. It has no finished marker. This does not establish a
complete zero-result archive scan and cannot safely be translated into a
successful empty Newznab feed. See `session-no-match-control.html` in evidence.

Automatic login is also not established: the browser passed `/login`'s security
check, but independent HTTP requests returned challenge 403, even with refreshed
clearance. The login page warns of an IP block after one wrong login. No password
was submitted. See [authentication and limits](authentication-and-limits.md).

Session-authenticated independent detail requests for April 2026 and January
2026 releases recovered 5040 TV/HD and 5020 TV/Foreign respectively, with
405.30 MB and 1.44 GB displayed sizes. These are **rounded sizes**, not exact
bytes. The item-specific Category field is separate from the navigation menu.
This proves a historical enrichment route exists, at one extra request per
release, but does not establish its cost, longevity, or completeness at scale.

### Can Prowlarr forward titles without categories?

The title is parsed independently of category. The interactive Search endpoint
uses `interactiveSearch=true`
(`src/Prowlarr.Api.V1/Search/SearchController.cs:172`), allowing uncategorized
results to be displayed. The Newznab endpoint used by downstream apps passes
`false` (`src/Prowlarr.Api.V1/Indexers/NewznabController.cs:180`); uncategorized
results then fail `IsValidRelease`. Thus manual visibility and automated
forwarding have materially different requirements.

Missing enclosure size is parsed as **zero**, not null
(`src/NzbDrone.Core/Indexers/RssParser.cs:290`). Do not conflate the null-size
validation rule with this specific API payload. Zero can reach interactive
results but is not known release size and may fail downstream size filters.
Neither a guessed TV/Movie category nor a made-up size is an acceptable fix.

A manually selected release may still be retrievable using its NZB link; that
specific Prowlarr path has not yet been exercised. The earlier direct NZB fetch
does not prove a Prowlarr grab, app sync, or Usenet-client download. Prowlarr's
`src/NzbDrone.Core/Download/NzbValidationService.cs:20` checks XML, root name,
error payloads and the presence of files; it does not validate segment numbering.

## Categories and metadata

[site-categories.json](evidence/site-categories.json) captures 60 category IDs
and labels from site navigation. This is a hierarchy reference, **not release
metadata**. RSS fixtures preserve item descriptions separately.

All 50 items in each sampled RSS response contained one numeric item-category
link. TV parent feed contained 5020/5040/5060; PC contained 4010/4050; Movies
contained 2010/2030/2040/2045; UHD-TV contained only 5045. The combined feed
contained only descendants of its two requested parents. Exact sizes agree
between `newznab:attr size` and enclosure length. Description sizes are rounded
and must not replace exact byte values.

Three browser detail checks matched RSS item metadata: SpongeBob → 5040 TV/HD;
Fan Ren Xiu Xian Zhuan → 2040 Movies/HD; Abyss School update → 4050 PC/Games.
Their displayed rounded sizes and dates also agreed. The historical Linux
detail supplied 4010 PC/0day and rounded 15.94 MB, absent from the API response.

This validates the extraction source in these samples, not all site assignments.
Anime episodes appear under both TV/HD and Movies/HD rather than consistently
under TV/Anime. Preserve upstream categories; do not silently correct them from
titles. Missing, conflicting, unknown or malformed metadata should produce a
visible error or an explicitly documented exclusion, never a guessed category.

Most familiar IDs align with Prowlarr, but not all:

| WTFNZB | Meaning | Prowlarr equivalent / issue |
| --- | --- | --- |
| 1090 | Xbox One | 1140; Prowlarr 1090 means Console/Other |
| 1100 | PS4 | 1180 |
| 8020 | Release-Info | Prowlarr 8020 means Other/Hashed; must not pass through |
| 8030–8060 | Reddit-Image, WtF-pOrN, 4chanImage, WtF-aNiMe | No exact standard equivalents established; custom categories or conservative parent-only mapping need explicit design |

Parent filtering must include known descendants, not equate category IDs solely
by number. An implementation can initially support only verified aligned TV,
Movies and PC categories. RSS enrichment covers **only the current returned
window**; joining it to the historical API does not solve missing metadata for
old releases. Downloading an NZB for every result would consume grab quota,
still would not establish categories, and is not selected.

## Prowlarr requirements (matching running source)

Paths below are relative to the Prowlarr source repository and pinned to the
commit above.

- `src/NzbDrone.Core/Indexers/Definitions/Newznab/NewznabCapabilitiesProvider.cs:42`
  requests caps with optional API key, follows redirects; line 95 parses XML,
  requires a `caps` root, and reads modes and category mappings. A valid RSS
  response is not a capabilities response.
- `.../Newznab/Newznab.cs:186` accepts basic `q` support for its capability
  test. There is no need to falsely claim movie IDs or TV episode support.
- `src/NzbDrone.Core/Indexers/HttpIndexerBase.cs:741` tests an empty basic search
  when RSS is supported and requires at least one parsed release. Passing this
  test does not exercise historical queries or NZB retrieval.
- `.../Newznab/NewznabRequestGenerator.cs:245` builds search parameters,
  categories, limits and offsets. Movie searches can fall back to basic `q`
  (line 49). Do not assume this makes restricted feed-window search complete.
- `.../Newznab/NewznabRssParser.cs:97` requires an NZB enclosure. Lines 143,
  194 and 207 handle categories, exact sizes and usenet dates. Categories are
  mapped using capabilities, not extracted from arbitrary HTML descriptions.
- `src/NzbDrone.Core/Indexers/HttpIndexerBase.cs:553` permits metadata issues
  in interactive searches but excludes missing size/category in other searches.
  Interactive visibility alone is insufficient evidence of downstream usability.
- `.../Newznab/NewznabRssParser.cs:30` maps error codes 100–199 to authentication
  errors, recognizes `Request limit reached`, and throws for other error XML.
- `src/NzbDrone.Core/Indexers/HttpIndexerBase.cs:227` retrieves NZB data and
  processes redirects; this is distinct from sending a job to a download client.

## Download validation limits

One recent TV release was fetched twice, once using the exact RSS enclosure and
once using conventional query-string credentials. Both were well-formed XML
with the NZB namespace, 21 files and 2,574 segments. **One segment had number 0
and one byte**, and its message ID differed between requests. Other sampled
structure matched. Thus XML/NZB structure and authenticated retrieval are
observed, but strict segment validity, article availability and successful
Usenet completion are not established. Do not rewrite upstream payloads without
understanding this behavior. No download client was invoked, no grab was sent
through Prowlarr, and no indexer was saved during discovery.

## Reproduction and remaining work

Use private local values for `WTFNZB_BASE_URL`, `WTFNZB_API_KEY`, and decimal
user ID. Construct requests in memory, redact redirect targets recursively,
never print URL-bearing exceptions, and cap response bytes before parsing.

1. GET `/api_fast` with `q=linux`, `apikey=key`, `r=key`, `i=base64(user ID)`.
   Vary only limit, offset, or cat; compare ordered GUIDs and metadata, not just
   HTTP status. Repeat baseline after any failure.
2. GET `/api?t=caps&apikey=key` without automatically following redirects;
   inspect the Location. Follow manually only after confirming safe origin/path.
3. GET `/rss` with `t=5000&dl=1&i=user ID&r=key`. Compare `num=1`, `num=100`,
   and `offset=50`; compare GUIDs to distinguish ignored parameters from change
   caused by incoming posts. Category 5045 and combined 2000,4000 are controls.
4. Parse item-scoped description links, exact sizes, and timezone-bearing dates;
   compare several distinct release types against browser details.
5. For a controlled NZB check, inspect one feed enclosure before fetching,
   never include `del=1`, and validate XML without submitting a download job.

Do not repeat the unbounded Unicode API probe. Test malformed/large responses
with local fixtures. Account restrictions, a numeric request budget, sustained
feed completeness, other credentials/accounts, deployment egress, and fully
successful grabs remain unverified. The observations support cautious recent
feed adaptation, not a promise of reliable archival automation.

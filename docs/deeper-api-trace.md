# Deeper endpoint tracing — 2026-09-19

## Result

**A session-authenticated TV catalogue is a new candidate for historical search.**
It avoids the custom streaming search and supplies categories in bulk. This is
more promising than an RSS-only adapter, but it is not yet a verified general
Prowlarr integration or a complete catalogue search.

An independent HTTP client using PHPSESSID fetched `/series/165800` in 914 ms.
The complete 6,520,485-byte HTML response contained **1,168 unique releases** for
Outlander: Blood of My Blood, dated August 8, 2025 through September 19, 2026.
Every row had a title, GUID, category, naive timestamp and displayed rounded
size. Categories included 5020, 5030, 5040, 5045, 5050 and 5060. Download links
were present but not fetched in this follow-up. The response ended with closing
HTML, unlike the ambiguous archive streams. Closing HTML proves response
completion, not exhaustive upstream indexing.

The first row is the current S02E01 release for which the archive query had
timed out. This establishes a distinct retrieval path with fresher results than
the sampled API corpus. See [summary](evidence/series-blood-summary.json) and
[two extracted rows](evidence/series-release-rows.html).

A second complete page, `/series/98794` (SpongeBob DocuPants), returned 63
unique releases in 520 ms, with dates from March 14, 2022 to March 20, 2026.
Its 391,288-byte response had categories 5030/5040 and no missing sampled
metadata fields. One season pack was labelled only 0.18 MB; upstream metadata
presence does not guarantee useful or accurate values. Preserve that distinction.

## Reproducible probes

Use the private origin and an existing authenticated PHP session. Do not follow
cart, subscription, NZB-client or download controls during discovery.

1. GET `/series?title=SpongeBob`: seven matching catalogue links, including
   `/series/8087`. GET `/series?title=Outlander`: three links, including
   `/series/165800` and `/series/173344` for variants of Blood of My Blood.
2. GET `/series/8087` with a bounded reader. The first 1 MiB contained 182 row
   starts with releases from October 2025 through August 2026 and categories
   5030/5040/5050/5080. The last row may be incomplete. This was deliberately
   cancelled at the byte limit; no completeness or oldest-date claim follows.
3. GET `/series/165800` with an 8 MiB decoded-body limit and 20-second timeout:
   complete result described above. No pagination links were present. Results
   are grouped by season/episode, not globally ordered by post date.
4. The first 2 MiB of `/series/173344` and `/series/165800` had matching first
   and last sampled GUIDs despite different displayed show titles. These aliases
   need deduplication; whole-response equality was not established.
5. GET `/series/8087?t=5045`, following an actual row category link's format:
   timed out after 20 seconds. Server-side category filtering is **unverified**.
   Local filtering of successfully retrieved rows is feasible.
6. GET `/series/98794` for the second complete historical sample. Followed one
   inspected `a.downloadnzb` link for a March 16, 2022 episode, using PHPSESSID
   only: HTTP 200 application/x-nzb, 182,785 bytes, well-formed NZB XML with
   13 files and 1,796 segments. One segment has number zero, as in the earlier
   recent-download sample. Article availability and actual downloading were not
   tested; no Usenet client was invoked. See the
   [NZB structure summary](evidence/historical-nzb-summary.json).

The title lookups took approximately 1.4 and 9.4 seconds respectively. This is a
small sample, not an availability benchmark. Large series pages exceed the
initial 2 MiB bound. An exploratory 8 MiB reader attempt recorded AbortError
without enough diagnostic state; its failure cause is inconclusive. It is
preserved in the probe log rather than attributed to the upstream server.

## Other routes checked

- `/api.php`, `/api_fast.php`, and `/search.php` returned 404.
- `/index.php?page=api&t=caps&apikey=REDACTED` redirected to `/api_fast`, losing
  the query. `/index.php?page=search&search=linux` redirected to `/_search_`.
  These alternate routes did not bypass the custom handlers.
- RSS `o=json` still returned XML with 50 items.
- `/release_info` is a separate release/pre-information catalogue. Inspected
  rows had names and scene categories but no NZB GUID/detail/download links.
  Its targeted episode query timed out after 20 seconds. It is not established
  as an NZB search backend.
- `/movies` and the site-linked `/movies?t=2045` each returned HTTP 200 with an
  empty body. That does not establish whether all movie routes are unusable.
- Site JavaScript references read-only `ajax_tvinfo`, `ajax_mediainfo` and
  `ajax_rarfilelist`, alongside mutating cart/admin/client operations. The latter
  were not requested; the metadata AJAX endpoints remain untested.

The site's paths and templates resemble nZEDb. Public reference code was read
at commit `68de9144ea51f16855eb93c584ee78b10ec2008c`, including its
[routing](https://github.com/nZEDb/nZEDb/blob/68de9144ea51f16855eb93c584ee78b10ec2008c/www/.htaccess)
and [series handler](https://github.com/nZEDb/nZEDb/blob/68de9144ea51f16855eb93c584ee78b10ec2008c/www/pages/series.php).
**This is an implementation hypothesis, not identification of WTFNZB's deployed
source/version.** For example, that handler requests 1,000 results, whereas the
observed site response contained 1,168. No reference source was copied here.

## Candidate integration and remaining checks

A TV query could resolve its show title through the catalogue, fetch the series
page once, then filter actual rows by season/episode/text/category. Cache show
resolution and parsed pages, deduplicate aliases and concurrent requests, and
share the same global limiter with RSS, authentication and downloads. This could
replace hundreds of detail requests with one larger page request. Do not crawl
all series or repeatedly fetch a multi-megabyte page for every episode query.

Still unverified: completeness for old seasons, coverage of other shows, title
normalization/ambiguity, exact size availability, timestamp timezone, stable
response limits, identifier mapping, automatic login, and Prowlarr end-to-end
behavior. Historical NZB retrieval is verified in one sample, with the structural
caveat above. A size-limited prefix must never masquerade as
a complete result list. Broad free-text/movie queries cannot be silently routed
to TV title search or answered with empty success.

The user subsequently confirmed that both TV and movie backlog search are
essential. TV catalogue adaptation is a candidate component, not an acceptable
standalone scope. General historical search still has the previously recorded
reliability blocker.
The series route means upstream clarification is no longer the only remaining
avenue. No runnable application or Prowlarr integration is claimed yet.

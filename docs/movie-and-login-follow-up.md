# Movie search and login follow-up — 2026-09-20

Investigation ran September 19, approximately 22:20–22:35 UTC (September 20 in
Europe/Copenhagen). **Both TV and movie backlog search are required.** TV-only
and RSS-only operation are not accepted substitutes. No adapter is implemented.

## Movie retrieval exists; reliable search remains unresolved

Independent requests used the existing PHP session, normal certificate
verification, sequential execution and approximately five-second minimum spacing.
Search POSTs reproduced the browser's multipart fields and
`X-Requested-With: XMLHttpRequest` header. Responses were bounded to 2 MiB and
20–45 seconds. One 503 was followed by a delayed, single recheck; no load test,
endpoint brute-force scan or state-changing cart/admin operation was performed.

| Probe | Observed result |
| --- | --- |
| Browser navigation to `/movies` | Empty page in the logged-in browser; not an independent-client-only failure. |
| `/movies?imdb=0133093` | HTTP 200, zero-byte HTML, consistent with earlier base/category movie-page probes. |
| `/movie/0133093?modal=1` | HTTP 200, Matrix film information. No release list or NZB search capability in this response. |
| Archive `The.Matrix.1999`, results=100 | 100 releases, explicit finished marker, 10.368 seconds. Sample post dates span August 2024–May 2026. |
| Same query, results=5 | Initial 503. Delayed recheck returned the byte-identical 100-result response in 10.372 seconds. A smaller requested limit did not reduce this sample. |
| `The Matrix 1999`, results=100 | 100 releases, finished marker, 10.461 seconds; 99 GUIDs overlap the dotted query. The additional title uses hyphens around its year. Syntax affects matching. |
| `Casablanca.1942`, results=100 | 67 releases, HTTP EOF after 24.475 seconds, no finished marker. Post dates reach April 2019. |
| Exact Casablanca repeat | **Four releases**, HTTP EOF after 2.468 seconds, no finished marker or error text. These are exactly the first four GUIDs from the 67-result response. The client allowed 45 seconds and did not abort. |
| Casablanca via direct `/_search_.php` | Same form on the direct script path returned 74 releases after 36.653 seconds, again without a finished marker. Changing the iframe path did not establish a reliable completion contract. |
| `/searchraw?search=The.Matrix.1999` | Search form HTML, no release results or meaningful completion indication. Not established as a working alternative. |
| `/sitemap` | Repeats API help, search, raw search and movie routes; also links statistics and previews. No separate historical movie API found in these links. |
| Site-linked `/stat-days.php` | Embedded daily aggregate counts for a chart, not release metadata/search. |
| Site-linked `/samples.php` | Timed out after 20 seconds before returning body bytes. Preview search capability remains unverified. |

The 67-versus-four result discrepancy is direct evidence of inconsistent movie
search results, independent of the meaning of the missing marker. HTTP completion
is not a guarantee of an exhaustive or stable application result. An absent
marker alone does not prove failure; neither may a short result list be assumed
complete. The direct-path result reinforces the uncertainty rather than repairing
it. We cannot diagnose the precise server-side termination cause from these
responses.

The Matrix detail request supplied actual category **2045 Movies/UHD**, displayed
size **54.59 GB**, and a matching post timestamp. A Casablanca detail for an
April 12, 2019 post also worked, supplying category 2045 and **246.22 MB**, with
an added date in April 2024. Post age and date added are different fields.
The surprisingly small movie size is upstream metadata, not a corrected or
guessed value. Category/size presence does not establish release quality.

One controlled NZB request for that older movie returned HTTP 200
`application/x-nzb`: well-formed NZB XML, ten files and 343 segments. One segment
has number zero, matching the earlier structural oddity. No Usenet client was
invoked, article availability was not checked, and no Prowlarr grab was performed.
See [structure summary](evidence/movie-nzb-summary.json).

## Implications for an adapter

A session-backed archive search plus detail lookup can retrieve real historical
movie releases. That is a viable mechanism for experimentation, **not established
reliable movie backlog support**. Repeating searches until a larger result set
appears would create unpredictable load without proving completeness. Missing
categories cannot be repaired by classifying a query as “movie.”

One detail request per candidate remains expensive. A small public page size,
bounded enrichment, caching and deduplication could reduce the cost per request,
but do not fix inconsistent candidate discovery or establish category-correct
pagination. An upstream-supported batch metadata/search endpoint would help.

Prowlarr source remains pinned to `12c327808314a7cae1b7301935ee10cabc19609f`.
`Newznab.cs:232` reads the provider's default page size from caps;
`NewznabRequestGenerator.cs:266` forwards an explicitly requested search limit.
`ManagedHttpDispatcher.cs:65` uses a supplied request timeout or a 100-second
default. The 15-second setting in `HttpIndexerBase.cs:719` belongs to
**ExecuteAuth**, not ordinary search. A slow metadata pipeline must fit the
actual caller's deadline; changing caps alone is not a request-budget solution.

The nZEDb reference
[movie handler](https://github.com/nZEDb/nZEDb/blob/68de9144ea51f16855eb93c584ee78b10ec2008c/www/pages/movie.php)
and [movie query implementation](https://github.com/nZEDb/nZEDb/blob/68de9144ea51f16855eb93c584ee78b10ec2008c/nzedb/Movie.php)
guided bounded route checks. They are not proof of WTFNZB's deployed source.
No upstream code was copied.

## Login test and local configuration correction

The user supplied login credentials in the ignored `.env`. Its permissions were
restricted to 0600. The browser automatically passed the `/login` challenge and
displayed the form. An independent client with the same browser user agent and
clearance cookie, but no PHP session, still received HTTP 403 challenge HTML.
No password was submitted through that independent client.

**One actual browser form submission was rejected:** “Incorrect username or
password.” The initial button locator failed before dispatch because the submit
element is a button, not an input; inspection corrected the locator before that
single submission. Automatic retries stopped at that point.

A local check then found that the password's unquoted `#` had been parsed as an
environment-file comment, truncating it. This should have been checked before
submission. The complete supplied value was quoted without displaying it; a
local parse/serialize round-trip verified exact preservation, and other settings
were unchanged. The configured username matched the existing session's name.

All upstream requests stopped after the rejection because the site warns of an
IP block after one wrong login. The user then filled the browser form manually
and explicitly requested submission. Its values were left unchanged. That
user-directed attempt reached a **Cloudflare error 1106 page explicitly stating
that the IP was banned**. No authentication success was observed. The earlier
truncated submission may have triggered the documented block; its precise
server-side cause and duration are not established.

Requests stopped again and browser task space 9 was handed back to the user.
Corrected-credential login, new-session acquisition, expiry recovery and
deployment-host automation remain unverified. The failed, truncated submission
is not evidence that the user's complete password is wrong or that supported
automatic login is impossible. No VPN or IP-rotation automation was performed.

## Remaining work

1. Extend the successful corrected login check below to fresh-session acquisition
   and expiry recovery in the intended deployment environment. Check secret
   parsing before any submission and latch failures to prevent retries.
2. Obtain a trustworthy archive completion/continuation contract or another
   working movie search route. The prepared upstream report includes concrete
   67/four/74-result evidence; it has not been sent.
3. Once both required search routes are viable, initialize the requested stack,
   implement the strict typing/CI/hook policy, and validate through Prowlarr.
   Passing caps or showing a few known releases is insufficient.

Sanitized requests and timings are in [probes.json](evidence/probes.json).
`archive-casablanca-67.html` and `archive-casablanca-4.html` retain the differing
real responses; `archive-matrix-100.html` retains a completed capped response.

## Corrected login succeeded after access was restored

At approximately 22:50 UTC on September 19 (September 20 local time), the user
reported changing their VPN address and explicitly requested another attempt.
The agent did not operate the VPN. Browser GET `/login` showed the ordinary
login form with no challenge or ban. Before submitting, the quoted password was
checked for lossless parsing and both filled form values were compared exactly
with the local configuration, without displaying them.

**One submission succeeded:** the browser navigated to `/`, showed logged-in
controls and had no login form or rejection. PHPSESSID did not change. An
independent HTTP client using that PHP session alone then read the protected
2019 movie detail page: HTTP 200, complete HTML with the expected release's
download link and no login form, in 331 ms.

This verifies the corrected credentials in the existing browser context and
subsequent cookie use outside the browser. It does **not** establish fresh-session
acquisition, session rotation, expiry recovery or unattended operation from a
deployment host. The earlier IP-ban observation remains valid for the previous
address. Movie-search completeness is a separate, unresolved problem.

## Overnight implementation probes (September 20 local time)

A second independent client, curl with HTTP/2, received the same 67-result
Casablanca prefix but timed out after 45 seconds without a completion marker.
This is not explained solely by Node's HTTP client. Space-separated
`Casablanca 1942` also timed out, with 77 partial results. In contrast,
`Casablanca` completed in 6.791 seconds with 100 results: only seven titles
contained 1942 and most results were music. Broadening is therefore not an
exhaustive historical-film workaround. See
[overnight probe records](evidence/overnight-probes.json) and the sanitized
[title-only response](evidence/archive-casablanca-title-only.html).

The profile page exposed no timezone setting. RSS explicitly supplied `+0200`;
historical pages omitted offsets. Prototype live checks use Europe/Copenhagen
as a stated configuration assumption, not a verified site timezone.

A Matrix detail page (GUID ending `fe411c12`) assigns Movies/HD (2040) to a
2160p title and displays 29.66 GB. This is a separate release from the previously
sampled 54.59 GB Movies/UHD release. The adapter preserves the actual assignment.

A fresh DocuPants catalogue audit found four releases displaying `0.00 MB`.
The complete page contains 63 releases, but the final adapter omits those four
zero-size records and returns 59 before additional user filters. It does not
invent positive byte sizes. The [item-scoped fixture](evidence/series-zero-size-row.html)
covers that case.

The first adapter NZB check rejected an ordinary external document-type
**declaration**. The parser was corrected to use defusedxml: declarations are
accepted without fetching the DTD, while entity expansion/external entity access
are blocked. This was an adapter parser bug, not an upstream download failure.

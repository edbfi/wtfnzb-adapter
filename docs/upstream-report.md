# Draft upstream questions — not posted

I tested API/RSS and the reworked search on September 19, 2026, following the
September 8 update in forum thread 4699. RSS is returning current releases, and
authenticated NZB retrieval works. I am investigating a Prowlarr adapter.

Could you clarify these points?

1. Is `/api_fast` using the intended current dataset? Its feed says it searches
   the last 100,000 releases, but the observed dataset's post dates range from
   July 31 to August 7. A specific release present in September 19 RSS returned
   no API matches, including with a cache-busting parameter. The reworked search
   also returned old data for a broad Linux search despite the wrapper showing
   a September 8 re-index timestamp.
2. Is there an API-key-authenticated way to obtain a release's category and
   size? `/api_fast` results omit both; RSS contains exact size but blank category
   attributes. Its item description does contain the numeric category link.
   Session-authenticated details provide categories and rounded sizes.
3. Is the streamed search guaranteed to end with `class="finished"` on every
   successful query, including zero results? A session-authenticated search
   returned HTTP 200 with four results, then EOF without that marker. A retry
   produced nine results but exceeded a 25-second client timeout. The browser
   code displays completion on EOF even without the marker. Bootstrap GETs have
   also returned 502. An isolated retry with a 90-second allowance closed after
   48 seconds without the marker. A no-match control returned a `timeout-error`
   block after about 11 seconds. How should an API client distinguish a complete
   no-match scan from a timeout or partial response?
4. What request budget and session lifetime should an integration observe?
   Recovering metadata through one detail request per result could be expensive.
5. Are `limit`, `offset` and category filtering supported by `/api_fast`? Each
   parameter separately left a 22-result sample unchanged. RSS `num=1` and
   `num=100` both returned the same 50 identities, as did `offset=50`.
6. Is automated username/password login supported for integrations? The browser
   passed the login page's security check, while the HTTP client got 403. The
   page warns about blocking an IP after one wrong login, so I have not tested
   password submissions. Is there a supported token-based alternative for
   historical search and detail metadata that avoids repeated logins?
7. Is `/series/<internal ID>` intended to expose all indexed releases for a
   show, and are there supported pagination, episode or identifier filters? Two
   complete pages supplied historical releases and categories, one reaching
   2022. A large show exceeded our response bound; `/series/8087?t=5045` timed
   out. A supported bounded form would reduce both bandwidth and detail requests.
8. Can you check the movie catalogue and archive termination behavior? `/movies`
   is blank in the logged-in browser and independent HTTP client, including
   category and IMDb variants. `/movie/0133093?modal=1` supplies film information.
   `The.Matrix.1999` archive search returned 100 results with a finished marker,
   but identical `Casablanca.1942` requests returned 67 and then four releases
   with normal HTTP EOF, no marker and no error. The four are the prefix of the
   67. The direct script URL returned 74 without a marker. All requests used the
   same PHP session, multipart fields and the browser's AJAX header; the client
   did not abort these responses. Is there a supported continuation mechanism
   or another movie search endpoint?

One additional correctness issue: a non-ASCII API query returned 100,000 items
and roughly 96.6 MB rather than matching results. I have not repeated it; further
probes have strict byte and time limits. No API keys, cookies or private hostnames
are included in this report.

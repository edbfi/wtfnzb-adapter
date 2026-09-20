# wtfnzb-adapter

Experimental Newznab adapter for WTFNZB and Prowlarr, using Python 3.14,
Litestar, Granian and msgspec. It runs, but **reliable, comprehensive movie
backlog search remains blocked by upstream search behavior**. Both movie and TV
backlog support are requirements; this prototype does not redefine that goal as
RSS-only support.

## What works, and where it stops

| Operation | Implemented behavior | Limit |
| --- | --- | --- |
| RSS / empty search | Real categories, exact byte sizes, timezone-aware dates | Current upstream window, normally 50 releases; no background collection |
| TV text search | Resolve an exact catalogue title, fetch historical releases, filter season/episode/category locally | Ambiguous titles fail; catalogue must fit 8 MB and contain a complete page. Rounded zero-size rows are omitted; coverage varies by show |
| Movie/general text search | Session-backed archive search plus real detail metadata | Completion marker required; at most 100 upstream candidates, first five text matches enriched. Category filtering follows enrichment and can return fewer than five |
| Pagination | Stable cached snapshot, local offset/limit | Does not page through the whole upstream archive |
| NZB retrieval | Authenticated, bounded XML validation and passthrough | Article availability and Usenet-client grabs are untested |
| Session capture | Optional local Ego Lite helper reads credentials/cookie privately | Existing session capture verified; unattended fresh-session/expiry recovery remains unverified |

Movie searches that truncate, time out, or produce an ambiguous no-result response
return an error. HTTP 200 by itself is insufficient. The stale `/api_fast` dataset
is not used as a fallback. A completed movie query worked live; another movie's
year-qualified query repeatedly failed. A title-only query completed but contained
mostly unrelated music, so the adapter does not silently broaden queries.

Historical sizes are estimates converted from the site's rounded display. Site
categories are preserved by meaning, including odd assignments; titles are not
used to invent categories. The configured historical timezone is an operator
assumption because those pages omit offsets. RSS retains its explicit offset.

See [findings](docs/findings.md), [implementation decisions](docs/implementation-scope.md),
[validation](docs/validation.md), and [remaining work](docs/project-plan.md).

## Local setup

```sh
uv sync --locked
uv run --locked prek install
```

Create a **mode-0600**, ignored `.env`. Quote passwords containing `#` and disable
shell interpolation when writing secrets. The application uses dotenv parsing
with interpolation disabled; environment variables override the file.

```dotenv
ADAPTER_API_KEY="a-separate-random-secret-at-least-24-characters"
ADAPTER_PUBLIC_URL="http://adapter-host:8765"
ADAPTER_STATE_DIR="/absolute/private/path/to/state"
WTFNZB_AUTH_FILE="/absolute/private/path/to/state/auth.json"
WTFNZB_SITE_TIMEZONE="Europe/Copenhagen"
```

Choose the timezone deliberately; the example matches observed summer RSS offsets
but the site's winter timezone has not been established. Use an adapter URL
reachable from Prowlarr. Keep the service on a trusted network or behind HTTPS;
do not log query strings at the reverse proxy, since Newznab uses API-key URLs.

The protected auth JSON file has four string fields:

```json
{
  "base_url": "WTFNZB_BASE_URL",
  "api_key": "WTFNZB_API_KEY",
  "user_id": "DECIMAL_USER_ID",
  "session": "PHP_SESSION_COOKIE_VALUE"
}
```

The base must be an HTTPS origin. The file must be mode 0600. It is read again
before upstream requests, so an atomic replacement is picked up without restarting.
The optional helper creates this file without copying cookies manually:

```dotenv
WTFNZB_BASE_URL="https://your-private-wtfnzb-origin"
WTFNZB_USERNAME="your-login"
WTFNZB_PASSWORD="your-exact-password"
WTFNZB_AUTO_SESSION="false"
```

With Ego Lite running, the helper creates one dedicated task space and remembers
its ID. It reuses that space on later calls and stops if the user takes control.
Advanced use can select an existing authorized agent-owned space with
`WTFNZB_EGO_SPACE` and `WTFNZB_EGO_PAGE`. Creation/recovery of a new dedicated space
is not yet live-validated; the tested export used the existing research space.

Run:

```sh
uv run --locked wtfnzb-session
uv run --locked litestar --app wtfnzb_adapter.app:create_app run --host 0.0.0.0 --port 8765 --workers 1
```

The standalone helper requires the service to be stopped so it can acquire the
same instance lock. It first tries the existing authenticated API help page. Only
if the actual login form appears does it fill the configured credentials, verify
the exact field values, and submit once. It writes a failure latch **before**
submission. Challenges and changed forms require human action. It respects Ego's
user-control stop and does not claim user-owned spaces, rotate IPs, or clear cookies.

Setting `WTFNZB_AUTO_SESSION="true"` opts into the same helper after a session/access
failure, on a subsequent uncached request. This is **experimental local browser
assistance**, not a verified unattended deployment solution. Keep it off until
expiry recovery has been tested on the deployment host. A failed helper attempt
creates `login-blocked` in the state directory. Inspect the browser and correct
the cause before removing that latch; never use an automated reset loop.

Environment variables and mode-0600 files protect against accidental disclosure;
they are not encryption at rest. An external secret manager or `age` can decrypt
into a restricted runtime file before startup. The app does not persist passwords
in its auth file or invent its own encryption scheme.

## Prowlarr configuration

Use **Generic Newznab**, the adapter base URL, API path `/api`, and the **adapter**
API key. Do not put the upstream key or private WTFNZB origin in Prowlarr's indexer
URL. The adapter advertises basic text, movie text, and TV text/season/episode
search. Identifier searches are rejected explicitly.

Keep Prowlarr’s Usenet Redirect setting enabled (this version requires it). Its
download URL redirects to the authenticated adapter NZB endpoint.

TV-only category requests also use the catalogue when Prowlarr rewrites them to
`t=search`. An exact catalogue title is required.

Start with manual searches and a conservative sync interval. Test a movie query,
a TV catalogue title, and an empty RSS search before enabling application sync.
A green Add Indexer test does not prove historical coverage or downloads.
[Validation notes](docs/validation.md) distinguish local checks from the user's
running Prowlarr instance. No job has been sent to a Usenet client.

## Upstream load and operation

The current runtime targets macOS/Linux (POSIX file locking). One process/worker owns a file lock and all upstream requests. Defaults are one
request at a time, at least 10 seconds between starts, at most 60 logical operations
per hour and 500 per day, persisted across restarts. These are conservative local
limits, **not a documented WTFNZB allowance**. Do not run replicas or separate state
directories against the same account to multiply them.

RSS cache: five minutes. Search snapshots: 30 minutes, at most 64 queries. Detail
metadata: one day, at most 1,000 releases. Failed searches: two minutes. Concurrent
searches are serialized and deduplicated through the cache. No crawler, periodic
RSS collector, database, or download client is configured. Browser refresh reserves
three logical operations; browser assets are not counted individually.

HTTP failures are not retried automatically. Rate limits honor `Retry-After` and
persist cooldowns. Reads and searches have byte/time bounds. Authentication errors
latch until credentials change or the optional helper succeeds. A cold archive
search can take roughly one minute due to metadata recovery and spacing. Queued
or slow searches can hit the 85-second adapter deadline and return an error.

## Development

```sh
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked python tools/check_basedpyright_config.py
uv run --locked basedpyright
uv run --locked pytest
uv run --locked prek validate-config prek.toml
uv run --locked prek run --all-files
uv build
```

Both Git hook stages are installed. The pre-commit gates always check the whole
project, including configuration-only changes; direct commits to `main` are blocked.
Use Conventional Commits. CI also runs tests and builds without live credentials.

**Typing warnings require code fixes.** No global diagnostic overrides, baselines,
competing configurations, file-wide pragmas, or blanket ignores are permitted.
The only exception is a justified, rule-specific inline
`# pyright: ignore[reportRule] -- justification` at a genuinely untyped third-party
call site, subject to review. See [typing policy](docs/typing-policy.md).

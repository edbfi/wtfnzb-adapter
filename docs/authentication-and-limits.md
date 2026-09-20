# Authentication and upstream request budget

These are requirements and candidate design choices, **not implemented features**.
They incorporate the user's preference for automatic cookie acquisition and
renewal, safe credential configuration, and low cost to WTFNZB.

Latest follow-up: a password submission was truncated by an unquoted `#` in
`.env` and rejected. The quoting was corrected and verified locally. A later
user-directed browser attempt reached Cloudflare 1106 with an explicit IP-ban
message. See the [incident and movie investigation](movie-and-login-follow-up.md).
After the user restored access and explicitly resumed testing, one submission
with the corrected values succeeded. PHP-session reuse in an independent HTTP
client also succeeded. Fresh-session acquisition and unattended expiry recovery
remain unverified; no automatic retry or IP rotation is planned.

## What login inspection established

On September 19, `/login` initially returned HTTP 403 challenge HTML to both an
independent HTTP client and browser fetch. Normal browser navigation passed the
automatic security verification and displayed a login form. The existing session
was not logged out and no credentials were submitted.

The form posts to `/login` with `username`, `password`, and optional hidden
`redirect`. No hidden CSRF field was present in that inspected form; this does
not prove no other login checks exist. The page warns:

> WARNING! One wrong login and your IP will be blocked :)

An independent client given the refreshed browser clearance cookie still got
HTTP 403 on `/login`. Existing PHP sessions worked for search/detail requests.
Consequently, acquiring a new session and using an existing one are separate
capabilities. Password login, successful automatic refresh, deployment-host
challenges, and unattended browser login remain **untested**. No bad-password
probe was attempted. Do not promise that username/password environment variables
alone solve Cloudflare or session expiration.

## Credential handling

- Prefer read-only secret files supplied by the deployment platform. Environment
  variables can point to those files. Direct environment values may be supported
  for simple installations, but environment configuration is not encryption.
- Keep credentials, cookies, private origin, redirect URLs and request bodies
  out of logs, exception messages, tracing, fixtures and public responses.
- Obtain credentials at runtime and keep active cookies in memory. If session
  persistence across restarts is justified to reduce logins, protect it as a
  credential store with restricted access, atomic writes and explicit expiry.
- `age` can encrypt a configuration file at rest. Decryption needs a separately
  provisioned identity; placing the ciphertext and its unrestricted key together
  does not protect against compromise of that running host. Prefer decrypting
  during deployment into a restricted ephemeral secret mount. Do not build a
  custom encryption scheme or embed the decryption key in the application.
  See [age's official usage documentation](https://github.com/FiloSottile/age#usage).
- Do not put passwords in command arguments, shell history, the repository, or
  this conversation. Actual variable names and deployment instructions remain
  to be selected once the authentication path is validated.

## Session lifecycle requirements

1. Reuse a valid session; do not log in before each search or periodically just
   because a timer fired. All upstream activity shares the same request budget.
2. Treat an explicit login redirect differently from a generic 403, 502 or
   search timeout. An outage must not trigger a password-submission loop.
3. Allow only one refresh operation at a time; concurrent searches must not all
   submit the same credentials. Pause upstream work while authentication is
   unresolved, with bounded waiting for callers.
4. Submit a verified credential set at most once per refresh attempt. A rejected
   login stops automatic attempts until the operator corrects the configuration
   and explicitly resets the failure. Given the site's warning, even the first
   attempt requires known-correct credentials; no probing or guesses.
   Validate secret-file parsing locally before submitting anything. For `.env`,
   reject ambiguous unquoted values containing `#` and explain how to quote
   them; never silently submit the truncated value. A ban also latches the
   failure state until access is restored and an operator explicitly resets it.
5. Confirm authenticated behavior after login before publishing the new session.
   Replay an interrupted read at most once. Never automatically repeat an NZB
   download as part of session recovery; it may consume grab quota.
6. If ordinary HTTP login is unavailable, consider a browser used only for
   session acquisition/renewal, then hand its authenticated session to the HTTP
   client. Verify this from the deployment host first. A human-required challenge
   becomes an explicit authentication-required state, not a retry loop or a
   purportedly successful login.

## Request limiting requirements

There is no confirmed numerical quota for this account. The profile shows VIP
and counters, not a verified budget. Do not describe any locally chosen limit
as the site's approved quota.

- A single account-wide limiter must cover API, RSS, search bootstrap/POST,
  details, login and downloads. Start with one in-flight request and no bursts;
  determine spacing and hourly/daily caps with the user/site before deployment.
- Multiple application workers or replicas must not multiply that budget.
  Initially use one worker/instance; cross-process coordination would require an
  explicit shared limiter before scaling.
- Honor `Retry-After` and stop on 429. Apply capped backoff and a cooldown after
  repeated upstream failures. Never retry authentication failures indefinitely.
  Retries consume budget and are bounded; downloads are not retried by default.
- Bound response bytes, duration, queued work, candidate count, and **metadata
  requests per user query**. Estimate the work before starting enrichment. One
  100-result archive search needs roughly 102 requests if every result needs a
  detail page: one bootstrap, one search, and 100 details. That is not a cheap
  proxy operation and must not be the default unnoticed behavior.
- The newly found TV series route returns metadata in bulk. Cache a successfully
  parsed series page across episode searches instead of repeating multi-megabyte
  fetches. One completed sample was 6.52 MB; request counts alone are therefore
  insufficient. Bound decoded bytes and response time as well, and reject a
  size-limited prefix rather than returning it as complete search results.
- Reuse parsed RSS metadata and cache successful immutable release metadata by
  GUID. Deduplicate concurrent identical searches and detail fetches. Bound
  caches; no archive-wide crawling or backfill and no periodic collection unless
  its usefulness and request budget are established.
- Do not cache timeouts, invalid credentials, truncated HTML or upstream errors
  as empty results. Do not silently drop unknown categories merely to avoid
  metadata requests. If the required work exceeds budget, return an explicit
  limit/temporary-unavailability error rather than an inaccurate success.
- Local health checks must not contact WTFNZB. Credential-free counters can
  report upstream requests, cache hits, remaining budget, cooldown, and session
  state without exposing titles or private URLs.

## Validation before implementation can be called reliable

Use local fake-clock tests for spacing, concurrency, queued limits, budget
exhaustion, cooldown, `Retry-After`, and shared refresh. Use simulated login
failures to test the failure latch; do not test wrong credentials on WTFNZB.
Assert that secrets never enter logs or public response bodies.

Then perform one controlled correct-credential login and expiry/recovery check
from the intended deployment environment. This requires a known-correct login
provided securely, not trial credentials. This work does not resolve the separate
[historical search reliability findings](findings.md); both gates must pass.

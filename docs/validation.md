# Validation — September 20, 2026 (Europe/Copenhagen)

This document separates successful prototype checks from deployment and upstream
reliability. No Usenet client received a job. No indexer was saved in the user's
Prowlarr instance.

## Runtime and dependency baseline

Initialized with `uv init --build-backend uv --name wtfnzb-adapter --python 3.14`.
Standard CPython 3.14.3 was selected by uv; `.python-version` is `3.14` and
`requires-python` is `>=3.14`. Build backend: uv_build 0.12.17. Resolved dependencies
are in `uv.lock`: Litestar 2.24.0, litestar-granian 0.16.0, Granian 2.8.3,
msgspec 0.21.1, HTTPX 0.28.1, Beautiful Soup 4.15.0, defusedxml 0.7.1,
python-dotenv 1.2.3. Development: Ruff 0.16.8, basedpyright 1.40.1, pytest 9.1.1,
AnyIO 4.15.1, prek 0.5.3 and defusedxml stubs.

Granian is started through the Litestar CLI and GranianPlugin. The instance lock
is acquired during application lifespan, not factory import: the CLI and worker
both inspect the application factory, so acquiring it earlier caused a false
second-instance error during the first smoke test. This was corrected and the
real server starts successfully with one worker.

## Live adapter checks

- API-key-protected caps and RSS returned valid XML; RSS returned 50 releases.
- `movie`, query `The.Matrix.1999`, Movies parent category: four eligible releases
  from the five enriched candidates, in about 61 seconds. Historical dates and
  actual detail-page categories/sizes were preserved; size/timezone qualifications
  still apply.
- `tvsearch`, exact catalogue title `SpongeBob DocuPants`: initially 63 releases,
  including March 14, 2022. The subsequent size audit identified four `0.00 MB`
  entries. The final parser explicitly omits those rather than fabricating sizes.
- Browser session export succeeded. Corrected credential login had succeeded
  earlier in the existing browser context. The deployed-host/fresh-session/expiry
  cycle has not been demonstrated. Auto-session remains opt-in and experimental.
- The first NZB request exposed overly strict DTD rejection in the adapter. The
  corrected parser accepts normal declarations and forbids entity expansion.

The [adapter records](evidence/adapter-live-validation.json) include the initial
failed NZB attempt as well as subsequent checks, rather than rewriting history.

## Prowlarr

The user's running instance is **2.6.5.5623**. An unsaved Generic Newznab test
against the workstation LAN URL returned HTTP 400 with “Http request timed out”.
The adapter is not reachable at that address from the remote Prowlarr host.
This leaves deployment networking and validation on that actual instance open.
No tunnel, public service, or production indexer configuration was created.

For protocol isolation, the official **2.6.5.5623 osx-core-arm64** release was
started locally with an isolated temporary data directory, no applications and
no download clients. Its archive SHA-256 matched GitHub's published asset digest;
see [binary provenance](evidence/prowlarr-binary.json). The unsigned executable
needed an ad-hoc development signature on this Mac; no system security setting
was changed. The local API confirmed version 2.6.5.5623.

The isolated Generic Newznab connection test passed (HTTP 200), and saving the
indexer there returned HTTP 201. Prowlarr recognized the advertised categories,
including Xbox One/PS4 remapping and custom Other categories. Further downstream
search/download results are recorded in
[local Prowlarr validation](evidence/prowlarr-local-validation.json).

## Automated gates

Tests use sanitized real RSS, complete/partial archive responses, item-scoped
series/detail HTML, and temporary projects for forbidden typing configurations.
They cover XML translation, metadata/category conflicts, count mismatches, partial
streams, NZB declarations/entity rejection, rate limits, persistent auth latching,
cache reuse, bounded enrichment, zero-size handling, protected credential parsing,
and the mandatory basedpyright policy.

The typing checker, basedpyright, Ruff, pytest, lock check, prek configuration,
shared hooks and package build are run locally. Both Git hook stages are installed.
CI repeats project-wide gates, tests and build without live service access. Final
command results are recorded after the validation run below.

## Final integration observations

The isolated Prowlarr downstream Newznab API returned **59 historical TV releases**
(the 63 upstream rows minus four rounded zero-size entries) and **50 RSS items**,
both HTTP 200. The oldest retained TV result was March 15, 2022. Prowlarr parsed
and forwarded real titles, sizes, dates and categories. Movie search subsequently
hit a real incomplete upstream response. Prowlarr retried the adapter and then
briefly disabled the indexer; the adapter's two-minute failure cache prevented
those retries from repeating the failed upstream operation. This is a confirmed
reliability limitation, not a successful movie-search validation through Prowlarr.

Source tracing explained the first TV test failure: `NewznabRequestGenerator.cs`
lines 128–191 (local source commit `12c327808314a7cae1b7301935ee10cabc19609f`)
rewrites TV queries without IDs/season/episode to basic `t=search`. The adapter now
routes explicit TV-only category requests to the catalogue as well. A focused
regression test covers this observed Prowlarr behavior.

Prowlarr requires Redirect for Usenet indexers. Attempting to turn it off in the
isolated instance returned HTTP 400; the setting stayed enabled. Its `/1/download`
route returned HTTP 301 to the adapter. A controlled client followed only that
verified local adapter URL. The first attempt returned an adapter error; one
bounded follow-up after cooldown returned HTTP 200, 3,058 bytes, a normal DTD
declaration and eight NZB files. No download client was
involved. This validates the redirect-and-retrieve path, not article availability
or an actual grab through Sonarr/Radarr.

Shared whitespace hooks normalized trailing whitespace and final newlines in
sanitized fixtures. Recorded response SHA-256 values describe the original private
responses, not these redacted and whitespace-normalized copies.

Final local results: **65 tests passed**, basedpyright reported **zero errors and
zero warnings**, Ruff formatting/lint and the configuration checker passed,
`uv lock --check` passed, prek configuration validated, and `uv build` produced
both sdist and wheel. Wheel inspection confirmed the category data, Ego helper
and license are included. Both Git hook shims are installed. Shared hooks' first
run fixed fixture whitespace; those changes were reviewed before re-staging.

After re-staging the reviewed changes, **every prek pre-commit hook passed**,
including Gitleaks and branch protection. The pinned Conventional Commits hook
also passed a separate `commit-msg` invocation. No commit was created. Temporary
servers were stopped and private research files were removed; only restricted,
ignored runtime credentials/state remain locally.

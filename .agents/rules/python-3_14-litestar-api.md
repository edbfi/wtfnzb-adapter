---
type: "agent_requested"
description: "Litestar + Granian + msgspec on Python 3.14 coding guidelines"
---

# Litestar on Python 3.14: Granian, msgspec, and a Rust-fast async core

Litestar is a batteries-included, class-first ASGI framework whose serialization, validation, and DTO layers are built directly on msgspec, so the highest-leverage skill on this stack is writing plain `msgspec.Struct` schemas and letting the framework encode, decode, validate, and document them without a second modeling library. Paired with Granian — a Rust (Tokio/Hyper) HTTP server that speaks ASGI/RSGI/WSGI — the runtime cost of an endpoint collapses to your handler body plus a near-zero (de)serialization pass. On Python 3.14 the toolchain is uniformly current: uv manages the environment and lockfile, Ruff lints and formats, and basedpyright type-checks in its strict-by-default `recommended` mode.

The way agents write wrong-but-plausible code here is almost always by importing habits from FastAPI/Pydantic or Flask: reaching for `pydantic.BaseModel` when a `msgspec.Struct` is the native type; wrapping every handler payload in a DTO when Litestar already accepts and returns Structs directly; declaring blocking `def` handlers or running blocking I/O inside `async def` and starving Granian's event loop; calling the bare `granian` CLI instead of `litestar run` with the plugin installed; and treating Python 3.14's JIT and free-threaded builds as production defaults when they are opt-in/experimental. Optimize for typed Structs, thin async handlers, dependency injection over globals, and the framework's own testing and OpenAPI machinery.

## Environment, tooling, and project layout

uv owns the interpreter, the virtual environment, and the lockfile. Pin the interpreter with a `.python-version` file containing `3.14`, declare `requires-python = ">=3.14"`, and keep runtime and dev dependencies separated with a standard `[dependency-groups]` table. The lockfile (`uv.lock`) is committed; CI runs with `--locked` so a stale lock fails loudly instead of silently re-resolving.

```toml
# pyproject.toml
[project]
name = "bookstore"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "litestar[standard]>=2.24",
    "litestar-granian>=0.15",
    "granian>=2.8",
    "msgspec>=0.21",
    "advanced-alchemy>=1.0",
    "aiosqlite>=0.20",
]

[dependency-groups]
dev = [
    "basedpyright>=1.39",
    "ruff>=0.16",
    "pytest>=8.3",
    "anyio>=4.6",
]

[tool.uv]
# uv reads dependency-groups automatically; `dev` is synced by default.

[tool.ruff]
target-version = "py314"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "SIM", "TC", "ASYNC", "RUF"]
# E501 is handled by the formatter; do not double-report line length.
ignore = ["E501"]

[tool.ruff.lint.isort]
known-first-party = ["bookstore"]

[tool.ruff.format]
quote-style = "double"

[tool.basedpyright]
pythonVersion = "3.14"
typeCheckingMode = "recommended"
include = ["src", "tests"]
# Third-party stubs are frequently incomplete; silence the noisiest cross-boundary rule.
reportMissingTypeStubs = false
```

`litestar[standard]` pulls in the CLI and uvicorn; installing `litestar-granian` and `granian` makes `litestar run` use Granian instead. Everyday commands:

```bash
uv sync                     # create/refresh .venv from the lockfile
uv add msgspec              # add a dependency and update pyproject + lock
uv lock --check             # CI gate: fail if lock is stale
uv run litestar --app bookstore.app:app run --reload   # dev server (Granian)
uv run ruff format .        # format
uv run ruff check --fix .   # lint + autofix
uv run basedpyright         # type-check
uv run pytest               # tests
```

`target-version = "py314"` is a valid Ruff target and drives `UP` (pyupgrade) toward 3.14-appropriate syntax; it does **not** change your deployment floor — it tells the linter which syntax is safe to emit. basedpyright's `recommended` mode is its default and is materially stricter than pyright's `standard`: it enables `reportAny`, `reportExplicitAny`, `reportUnusedCallResult`, `reportImplicitStringConcatenation`, and more, reports lower-severity rules as warnings, and sets `failOnWarnings` so the CLI exits non-zero on any warning. Do not silence a whole rule globally to quiet one line — use a scoped `# pyright: ignore[reportAny]` with the rule in brackets (basedpyright requires the bracketed rule via `reportIgnoreCommentWithoutRule`).

A layout that scales; treat it as illustration, not a mandate:

```text
src/bookstore/
    app.py            # Litestar() assembly, plugins, config
    controllers/      # class-based controllers grouped by resource
    domain/           # msgspec Structs (schemas) + service classes
    db/               # SQLAlchemy models, session config
    dependencies.py   # Provide() factories
    guards.py         # authorization guards
tests/
```

## msgspec Structs are the data model

A `msgspec.Struct` is a slotted, C-level type and is what Litestar uses internally for encode/decode/validate. Per the official msgspec docs, Structs "should feel familiar" to dataclasses/attrs users but are "5-60x faster for common operations" — the benchmarks break that down as roughly 4× faster than standard classes/attrs/dataclasses for instance creation and 5×–60× faster for order comparison. Define schemas as Structs and annotate constraints with `typing.Annotated[..., msgspec.Meta(...)]`; Litestar surfaces those constraints in the OpenAPI schema and enforces them on decode.

```python
from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

import msgspec

# Reusable constrained aliases
Isbn = Annotated[str, msgspec.Meta(pattern=r"^\d{13}$")]
Rating = Annotated[int, msgspec.Meta(ge=1, le=5)]


class Book(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    id: UUID
    title: Annotated[str, msgspec.Meta(min_length=1, max_length=200)]
    isbn: Isbn
    price_cents: Annotated[int, msgspec.Meta(ge=0)]
    tags: tuple[str, ...] = ()
    created_at: dt.datetime


class BookCreate(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    title: Annotated[str, msgspec.Meta(min_length=1, max_length=200)]
    isbn: Isbn
    price_cents: Annotated[int, msgspec.Meta(ge=0)]
    tags: tuple[str, ...] = ()
```

Key Struct options and when they earn their place:

- `kw_only=True` — keyword-only construction; makes call sites explicit and lets you add fields without ordering headaches. A sensible default for API schemas.
- `frozen=True` — pseudo-immutable (blocks attribute assignment, generates `__hash__`). Use for value objects and config you pass around; update with `msgspec.structs.replace(obj, field=...)`.
- `forbid_unknown_fields=True` — reject extra keys on decode instead of silently dropping them. Prefer for request bodies where a stray field signals a client bug.
- `omit_defaults=True` — omit fields equal to their default when encoding; smaller payloads and faster encode. Good for responses with many optional fields.
- `rename="camel"` (or a dict/callable) — wire names differ from Python names; e.g. emit `createdAt`. Applies to the whole Struct.
- `tag=True` / `tag_field=...` — discriminated (tagged) unions. Every member of the union must set a tag and share the same `tag_field` (defaults to `"type"`), or msgspec falls back to slow try-each dispatch and can mis-select an overlapping variant.
- `array_like=True` — encode as a JSON array rather than an object; use only for tight internal protocols where field order is fixed.

Tagged unions are the correct tool for heterogeneous payloads:

```python
import msgspec


class CardPayment(msgspec.Struct, tag="card"):
    amount_cents: int
    last4: str


class BankPayment(msgspec.Struct, tag="bank"):
    amount_cents: int
    iban: str


Payment = CardPayment | BankPayment
decoder = msgspec.json.Decoder(Payment)
payment = decoder.decode(b'{"type":"card","amount_cents":500,"last4":"4242"}')
```

For partial updates, use the `UNSET` sentinel with `omit_defaults=True` to distinguish "field absent" from "explicitly null":

```python
import msgspec
from msgspec import UNSET, UnsetType


class BookPatch(msgspec.Struct, omit_defaults=True, kw_only=True):
    title: str | UnsetType = UNSET
    price_cents: int | UnsetType = UNSET


patch = msgspec.json.decode(b'{"title":"New"}', type=BookPatch)
# patch.title == "New"; patch.price_cents is UNSET, so leave the column untouched.
```

Encode/decode directly when you are outside a handler (background jobs, message queues). Reuse `Encoder`/`Decoder` instances in hot paths — they cache the compiled codec:

```python
import msgspec

encoder = msgspec.json.Encoder()
decoder = msgspec.json.Decoder(Book)

raw: bytes = encoder.encode(book)
book = decoder.decode(raw)
```

Use `msgspec.convert` to coerce already-parsed builtins (e.g. a dict from another library) into a Struct with validation, and `msgspec.to_builtins` for the reverse when handing data to a protocol msgspec doesn't own. The msgspec docs report that it "decodes and validates JSON faster than orjson can decode it alone," and without schemas its raw JSON speed is on par with orjson — which is why a second JSON library is unnecessary here.

## Application assembly and routing

Litestar is class-first: group endpoints into `Controller` subclasses, compose them with `Router`s, and register everything on a single `Litestar` instance. Route handlers are decorated functions/methods (`@get`, `@post`, `@put`, `@patch`, `@delete`). Handlers should be `async def`; a synchronous handler runs in a threadpool unless you assert `sync_to_thread=False` for genuinely non-blocking sync code.

Plain Structs work directly as handler input and output — no DTO required. Litestar decodes the request body into the annotated Struct (validating constraints) and encodes the return value:

```python
from __future__ import annotations

from uuid import UUID

from litestar import Controller, Litestar, delete, get, post
from litestar.di import Provide
from litestar.exceptions import NotFoundException

from bookstore.domain.schemas import Book, BookCreate
from bookstore.domain.services import BookService


async def provide_book_service() -> BookService:
    return BookService()


class BookController(Controller):
    path = "/books"
    tags = ["books"]
    dependencies = {"books": Provide(provide_book_service)}

    @get()
    async def list_books(self, books: BookService, limit: int = 50, offset: int = 0) -> list[Book]:
        return await books.list(limit=limit, offset=offset)

    @get("/{book_id:uuid}")
    async def get_book(self, books: BookService, book_id: UUID) -> Book:
        book = await books.get(book_id)
        if book is None:
            raise NotFoundException(detail=f"No book {book_id}")
        return book

    @post()
    async def create_book(self, books: BookService, data: BookCreate) -> Book:
        return await books.create(data)

    @delete("/{book_id:uuid}", status_code=204)
    async def delete_book(self, books: BookService, book_id: UUID) -> None:
        await books.delete(book_id)


app = Litestar(route_handlers=[BookController])
```

Path parameters are typed inline (`{book_id:uuid}` → `book_id: UUID`); query parameters are any handler kwargs that are not path params, reserved names, or injected dependencies. `data` is the reserved name for the request body. Return `None` with `status_code=204` for deletes.

Reach for a DTO only when the wire shape must differ from the domain type — excluding secrets, renaming to camelCase, or accepting partial input. `MsgspecDTO` (and `DTOConfig`) drive these transformations declaratively:

```python
from uuid import UUID

from litestar import Controller, patch
from litestar.dto import DTOConfig, DTOData, MsgspecDTO

from bookstore.domain.schemas import Book


class BookReadDTO(MsgspecDTO[Book]):
    config = DTOConfig(rename_strategy="camel")


class BookPatchDTO(MsgspecDTO[Book]):
    config = DTOConfig(exclude={"id", "created_at"}, partial=True)


class BookController(Controller):
    path = "/books"
    return_dto = BookReadDTO

    @patch("/{book_id:uuid}", dto=BookPatchDTO)
    async def update_book(self, book_id: UUID, data: DTOData[Book]) -> Book:
        # data.create_instance() / data.as_builtins() apply only the provided fields.
        ...
```

Do not wrap a Struct you are using as-is in a DTO — `@post(dto=MsgspecDTO[BookCreate])` on top of a plain `data: BookCreate` handler is redundant and has historically produced confusing decode errors. Use a DTO for a transformation, a bare Struct otherwise.

Exceptions: raise Litestar's HTTP exceptions (`NotFoundException`, `NotAuthorizedException`, `PermissionDeniedException`, `ClientException`, `ValidationException`) and let the framework render RFC 9457 problem-detail responses. Register an `exception_handlers` mapping on the app or a layer only for cross-cutting translation of domain errors.

## Dependency injection, state, and lifecycle

Dependencies are declared with `Provide(factory)` and injected by matching the parameter name to the key. They can be layered on the app, router, controller, or handler; inner layers override outer ones. A dependency may itself depend on other injected values, and dependencies are injected into guards too.

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from litestar import Litestar
from litestar.datastructures import State
from litestar.di import Provide
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@asynccontextmanager
async def db_lifespan(app: Litestar) -> AsyncIterator[None]:
    engine: AsyncEngine = create_async_engine("postgresql+asyncpg://localhost/books")
    app.state.engine = engine
    try:
        yield
    finally:
        await engine.dispose()  # ownership is explicit: whoever creates, disposes


def provide_engine(state: State) -> AsyncEngine:
    return state.engine


app = Litestar(
    route_handlers=[],
    lifespan=[db_lifespan],
    dependencies={"engine": Provide(provide_engine, sync_to_thread=False)},
)
```

Prefer `lifespan` async context managers over the older `on_startup`/`on_shutdown` hook lists when a resource needs paired setup/teardown — the context manager guarantees cleanup and makes ownership obvious. `State` is a typed bag on `app.state`; access it in handlers/dependencies by declaring a `state: State` parameter. For per-request dependencies that hold a resource (a DB session, an HTTP client), yield from an async generator dependency so Litestar closes it after the response.

Guards are authorization callables that run before the handler and raise on failure:

```python
from litestar import Controller
from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler


def require_admin(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    user = connection.scope.get("user")
    if user is None or not getattr(user, "is_admin", False):
        raise NotAuthorizedException()


class AdminController(Controller):
    path = "/admin"
    guards = [require_admin]
```

## Concurrency on Python 3.14 and Granian's runtime

Handlers run on Granian's event loop; keeping that loop free is the single most important performance contract on this stack. Never call blocking I/O (a synchronous DB driver, `requests`, `time.sleep`, heavy CPU) inside an `async def` handler — it stalls every concurrent request on that worker. Use async drivers (`asyncpg`, `aiosqlite`, `httpx.AsyncClient`); for unavoidable blocking or CPU-bound work, offload to a thread with `anyio.to_thread.run_sync` or mark a sync handler with the default `sync_to_thread=True` so Litestar runs it in a threadpool.

Python 3.14 ships real concurrency upgrades, but weigh them honestly:

- **Free-threaded (no-GIL) CPython is officially supported.** The official "What's new in Python 3.14" states "PEP 779: Free-threaded Python is officially supported." PEP 779 frames this as Phase II — the free-threaded build is officially supported but still optional, shipping as a separate `3.14t` binary, with single-threaded overhead reduced to roughly 5–10% (down from ~40% in 3.13's experimental phase). Both msgspec and Granian publish free-threaded wheels. Granian's README nonetheless warns verbatim: "free-threaded Python support is still experimental and highly discouraged in production environments," and adds that "if for any reason the GIL gets enabled on the free-threaded build, Granian will refuse to start." Treat it as opt-in and benchmark first. Under Granian's free-threaded build, workers become threads within one interpreter rather than separate processes.
- **The experimental JIT** — per "What's new in Python 3.14," "Windows and macOS binary releases now support the experimental just-in-time compiler." It is off by default and must be enabled explicitly, and it does not run under free-threaded builds. Do not assume it in performance claims.
- **`concurrent.interpreters`** (PEP 734) exposes multiple interpreters in the stdlib — useful for CPU parallelism without multiprocessing overhead, but a specialized tool, not a default for request handling.
- **Deferred annotation evaluation** (PEP 649/749) is now the default: annotations are computed lazily, so `from __future__ import annotations` is no longer required for forward references, and `annotationlib` lets you introspect them as objects. Litestar resolves handler signatures through this machinery; keep referenced names importable at module scope.

Granian's threading model is distinct from Gunicorn/Uvicorn — do not copy their worker math. The knobs: `workers` are processes each holding a Python interpreter; `runtime_threads` are Rust threads per worker for network I/O; `runtime_blocking_threads` handle blocking OS operations; and on async protocols the Python-facing `blocking_threads` is effectively fixed at 1. The `runtime-mode` selects `st` (N single-threaded Rust runtimes, better for few processes) or `mt` (one multi-threaded runtime, scales on many cores), with `auto` picking for you. Match `workers` to available CPU cores and set a `backpressure` bound in production so traffic spikes queue rather than exhaust memory. Let Granian auto-tune the thread pools unless profiling says otherwise.

## Serving with Granian via the plugin

Install `litestar-granian` and add `GranianPlugin()`; the standard `litestar run` command then starts Granian (Rust HTTP core, native HTTP/2, lower memory) in place of uvicorn, while preserving Litestar's lifespan, signal handling, dev reload, and CLI flags. Drive the server through `litestar run` — never mix `GranianPlugin` with a separate hand-rolled `granian` invocation; the plugin owns the server lifecycle.

```python
from litestar import Litestar, get
from litestar_granian import GranianPlugin


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


app = Litestar(route_handlers=[health], plugins=[GranianPlugin()])
```

```bash
# Development: reload on change
uv run litestar --app bookstore.app:app run --reload

# Select an optional event loop (install the extra first)
uv add "litestar-granian[uvloop]"
uv run litestar --app bookstore.app:app run --loop uvloop
```

Granian's full option surface (workers, `--runtime-mode`, `--http`, `--backpressure`, `--ssl-certificate`/`--ssl-keyfile`, `--access-log`, Prometheus `--metrics`) is available on the `granian` CLI and via `GRANIAN_*` environment variables (e.g. `GRANIAN_WORKERS`, `GRANIAN_HTTP`, `GRANIAN_BACKPRESSURE`). Granian's real SSL flags are `--ssl-certificate` and `--ssl-keyfile` (PKCS#8 keys), and the runtime-mode values are `auto`/`mt`/`st`. For a Litestar deployment, tune workers to cores, keep `--http auto` unless a specific reason forces HTTP/2-only, and always set a backpressure bound.

## Data layer: Advanced Alchemy

For relational persistence, use Advanced Alchemy — the maintained SQLAlchemy 2.x companion that ships the Litestar integration, async repositories/services, Alembic wiring, and audited base classes. Import it from `advanced_alchemy.extensions.litestar`; the older `litestar.plugins.sqlalchemy` re-export is deprecated and scheduled for removal, so target Advanced Alchemy directly. Litestar deliberately does not and will not ship its own ORM.

```python
from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.extensions.litestar import (
    AsyncSessionConfig,
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from sqlalchemy.orm import Mapped, mapped_column


class BookModel(UUIDAuditBase):
    __tablename__ = "book"
    title: Mapped[str]
    isbn: Mapped[str] = mapped_column(unique=True)
    price_cents: Mapped[int]


class BookRepository(SQLAlchemyAsyncRepository[BookModel]):
    model_type = BookModel


class BookService(SQLAlchemyAsyncRepositoryService[BookModel]):
    repository_type = BookRepository


db_config = SQLAlchemyAsyncConfig(
    connection_string="postgresql+asyncpg://localhost/books",
    session_config=AsyncSessionConfig(expire_on_commit=False),
    before_send_handler="autocommit",  # commit on 2xx, rollback otherwise
    create_all=True,  # dev convenience; use Alembic migrations in production
)

alchemy = SQLAlchemyPlugin(config=db_config)
```

The plugin injects a request-scoped `AsyncSession` and manages transaction lifecycle via `before_send_handler`. `SQLAlchemyDTO` (also from Advanced Alchemy) bridges ORM models to the wire when you want to serialize a model directly; otherwise map models to msgspec Structs in your service layer to keep the transport schema independent of the table. Set `expire_on_commit=False` so returned objects remain usable after the autocommit handler fires. For schema changes, use Advanced Alchemy's Alembic integration rather than relying on `create_all`.

## OpenAPI and structured configuration

Litestar generates an OpenAPI 3.1 schema from your handler signatures and Struct annotations automatically. Configure it with `OpenAPIConfig`, and choose a docs UI through render plugins — Scalar is the modern default:

```python
from litestar import Litestar
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin

app = Litestar(
    route_handlers=[BookController],
    openapi_config=OpenAPIConfig(
        title="Bookstore API",
        version="1.0.0",
        description="Catalog service",
        render_plugins=[ScalarRenderPlugin()],
        path="/docs",
    ),
)
```

The schema is served at `path` (default `/schema`); constraints declared via `msgspec.Meta` (min/max, patterns, bounds) propagate into the schema, so precise Structs produce precise docs for free.

## Testing

Litestar ships an httpx-based test client. Use `AsyncTestClient` for async apps (it shares one event loop with your async fixtures and dependencies, avoiding the cross-loop errors that plague the sync `TestClient` when a handler holds an async resource); `create_test_client` is a convenient one-shot factory for small tests. Drive tests with pytest over anyio.

```python
from collections.abc import AsyncIterator

import pytest
from litestar.status_codes import HTTP_200_OK
from litestar.testing import AsyncTestClient

from bookstore.app import app

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[AsyncTestClient]:
    async with AsyncTestClient(app=app) as test_client:
        yield test_client


async def test_health(client: AsyncTestClient) -> None:
    response = await client.get("/health")
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"status": "ok"}
```

Entering the client's context (`async with`) triggers the app's lifespan, so startup/shutdown and any DB setup run exactly as in production. For WebSocket handlers, use `client.websocket_connect(...)`; for SSE/channels endpoints, fetch the plugin from `client.app.plugins.get(...)` and assert on the streamed events. Provide test doubles by overriding dependencies (`app.dependencies` / handler-level `dependencies`) rather than monkeypatching internals.

## Anti-patterns to avoid

| Wrong | Why it's wrong | Right |
| --- | --- | --- |
| `class Book(pydantic.BaseModel)` for schemas | Imports another validation library; msgspec is the native, faster engine Litestar already uses | `class Book(msgspec.Struct)` |
| `@post(dto=MsgspecDTO[BookCreate])` on a plain `data: BookCreate` handler | Redundant; Litestar decodes/validates bare Structs, and the extra DTO wrapper can raise opaque decode errors | Annotate `data: BookCreate` directly; use a DTO only to transform (exclude/rename/partial) |
| `def handler(): requests.get(...)` or blocking calls in `async def` | Blocks Granian's event loop and serializes all concurrent requests on the worker | `async def` + async client, or offload with `anyio.to_thread.run_sync` |
| Running the bare `granian ...` CLI alongside `GranianPlugin` | Two owners of the server lifecycle; loses Litestar lifespan/signal/reload integration | Install the plugin and use `litestar run` |
| Copying Gunicorn/Uvicorn worker/thread counts | Granian's process/Rust-thread architecture is different; wrong tuning wastes cores or memory | Set `workers` ≈ cores, pick `runtime-mode`, set a `backpressure` bound |
| `from litestar.plugins.sqlalchemy import ...` | Deprecated re-export slated for removal | `from advanced_alchemy.extensions.litestar import ...` |
| Tagged union members missing `tag=` | msgspec falls back to slow try-each dispatch and can mis-decode overlapping variants | Give every union member a `tag` and a shared `tag_field` |
| Sync `TestClient` with async resources in fixtures | Handler resources bind to a different event loop and error on cleanup | `AsyncTestClient` sharing the test's loop |
| Enabling free-threaded/JIT builds as the default | Free-threaded is experimental for production per Granian; JIT is opt-in and excluded under free-threading | Use the standard build; benchmark experimental builds before adopting |
| Global `# type: ignore` or blanket rule-disable to quiet basedpyright | `recommended` mode is strict on purpose; broad ignores hide real errors and violate `reportIgnoreCommentWithoutRule` | Scoped `# pyright: ignore[reportAny]` with the specific rule |

## Version & compatibility

| Component | Targeted release line | Notes / availability floor |
| --- | --- | --- |
| Python | 3.14 (3.14.7 stable) | Deferred annotations (PEP 649/749), t-strings (PEP 750), bracket-free `except` (PEP 758), `concurrent.interpreters` (PEP 734), `compression.zstd` (PEP 784), UUID 6/7/8 all shipped; free-threading officially supported (PEP 779, optional `3.14t` build); JIT experimental/opt-in on macOS + Windows |
| Litestar | 2.24 line | Requires msgspec; `litestar[standard]` includes CLI + server extras. A 3.x line is in development; this reference targets stable 2.x |
| Granian | 2.8 line | Requires Python ≥3.10; ASGI/RSGI/WSGI, HTTP/1+HTTP/2, `runtime-mode` auto/mt/st; free-threaded wheels experimental and refuses to start if the GIL re-enables |
| litestar-granian | 0.15 line | `GranianPlugin()`; integrates Granian with `litestar run`; `[uvloop]`/`[rloop]`/`[winloop]` loop extras |
| msgspec | 0.21 line | Python 3.14 support incl. free-threaded wheels; Structs, `Meta` constraints, tagged unions, `convert`/`to_builtins` |
| Advanced Alchemy | 1.x line | SQLAlchemy 2.x async; Litestar extension, repositories/services, Alembic |
| uv | 0.12 line | `uv sync` / `uv run` / `uv lock`; `[dependency-groups]`, `requires-python`, `.python-version` |
| Ruff | 0.16 line | `target-version = "py314"` valid; linter + formatter |
| basedpyright | 1.39 line | `recommended` mode default (strict; `failOnWarnings`); configured under `[tool.basedpyright]`; supports Python 3.14 |

- **Research date:** September 5, 2026

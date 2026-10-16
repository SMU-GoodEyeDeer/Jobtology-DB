"""Private dashboard. The HTTP process reads telemetry and enqueues fixed profiles only."""

# FastAPI registers nested handlers through decorators at runtime.
# pyright: reportUnusedFunction=false

from __future__ import annotations

import hmac
import threading
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from jobtology_db.admin.auth import COOKIE_NAME, LoginLimiter, SessionAuth
from jobtology_db.admin.config import ActionProfile, AdminSettings, load_profiles
from jobtology_db.admin.demo import demo_dashboard
from jobtology_db.admin.queue import JobStore, QueueConflict, public_job
from jobtology_db.admin.telemetry import DashboardCache, NativeTelemetry, service


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class EnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")


class AdminRuntime:
    def __init__(
        self, settings: AdminSettings, telemetry: Any = None, store: JobStore | None = None
    ):
        self.settings = settings
        self.auth, self.limiter = SessionAuth(settings), LoginLimiter()
        self.cache = DashboardCache(telemetry or NativeTelemetry(settings), settings.cache_seconds)
        self.store = store or JobStore(settings.queue_path)
        if settings.mode == "live":
            self.store.initialize()

    def profiles(self) -> tuple[list[ActionProfile], bool]:
        try:
            return load_profiles(self.settings.actions_file), True
        except Exception:
            return [], False

    def worker_available(self) -> tuple[bool, str]:
        try:
            worker = self.store.worker_status()
            if worker:
                age = (
                    datetime.now(UTC) - datetime.fromisoformat(worker["heartbeat_at"])
                ).total_seconds()
                if 0 <= age <= self.settings.worker_stale_seconds:
                    return True, "Host worker heartbeat is current."
            return False, "Host worker is offline or its heartbeat is stale."
        except Exception:
            return False, "Job queue is unavailable."

    def controls(self) -> tuple[list[dict[str, Any]], dict[str, ActionProfile], bool]:
        profiles, config_ok = self.profiles()
        worker_ok, worker_message = self.worker_available()
        reason = None
        if self.settings.mode == "demo":
            reason = "Synthetic demo actions are disabled."
        elif not self.settings.controls_enabled:
            reason = "Operator controls are disabled by configuration."
        elif not config_ok:
            reason = "Action configuration is unavailable or invalid."
        elif not worker_ok:
            reason = worker_message
        # Unknown jobs require deliberate operator resolution outside the dashboard.
        try:
            if self.store.has_pending():
                reason = "A pending or uncertain job requires operator attention."
        except Exception:
            reason = "Job queue is unavailable."
        actions = [
            {
                "id": profile.id,
                "label": profile.label,
                "description": profile.description,
                "kind": profile.kind,
                "enabled": reason is None,
                "disabled_reason": reason,
                "requires_confirmation": True,
            }
            for profile in profiles
        ]
        if not profiles:
            actions = [
                {
                    "id": "refresh-due",
                    "label": "Refresh due sources",
                    "description": "Ask the host worker to refresh sources that are due.",
                    "kind": "refresh_due",
                    "enabled": False,
                    "disabled_reason": reason or "No trusted action profiles are configured.",
                    "requires_confirmation": True,
                },
                {
                    "id": "load-jobkorea",
                    "label": "Load local JobKorea dataset",
                    "description": "Load a dataset prepared and pinned by the operator.",
                    "kind": "load_jobkorea",
                    "enabled": False,
                    "disabled_reason": reason or "No trusted local dataset profile is configured.",
                    "requires_confirmation": True,
                },
            ]
        return actions, {profile.id: profile for profile in profiles}, worker_ok


def create_app(
    settings: AdminSettings | None = None,
    *,
    telemetry: Any = None,
    store: JobStore | None = None,
) -> FastAPI:
    runtime: AdminRuntime | None = None
    runtime_lock = threading.Lock()

    def get_runtime() -> AdminRuntime:
        nonlocal runtime
        with runtime_lock:
            if runtime is None:
                # BaseSettings resolves required credentials from the environment.
                configured = settings or AdminSettings()  # pyright: ignore[reportCallIssue]
                runtime = AdminRuntime(configured, telemetry, store)
            return runtime

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        application.state.runtime = get_runtime()
        yield

    application = FastAPI(
        title="Jobtology administration",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def session(request: Request) -> dict[str, Any]:
        payload = get_runtime().auth.verify(request.cookies.get(COOKIE_NAME))
        if payload is None:
            raise HTTPException(401, "Authentication required.")
        return payload

    def csrf(request: Request, payload: dict[str, Any]) -> None:
        token = request.headers.get("x-csrf-token", "")
        if len(token) > 128 or not hmac.compare_digest(token, payload["c"]):
            raise HTTPException(403, "Invalid CSRF token.")

    def session_response(payload: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "authenticated": payload is not None,
            "username": payload["u"] if payload else None,
            "csrf_token": payload["c"] if payload else None,
            "mode": get_runtime().settings.mode,
        }

    @application.middleware("http")
    async def security(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith("/api/"):
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                configured = get_runtime().settings.origins()
                own_origin = f"{request.url.scheme}://{request.url.netloc}"
                origin = request.headers.get("origin")
                cross_site = request.headers.get("sec-fetch-site") == "cross-site"
                if cross_site or (origin and origin.rstrip("/") not in configured | {own_origin}):
                    return JSONResponse(
                        {"detail": "Cross-origin request refused."}, status_code=403
                    )
                try:
                    size = int(request.headers.get("content-length", "0"))
                except ValueError:
                    size = 16_385
                if size < 0 or size > 16_384:
                    return JSONResponse({"detail": "Request body too large."}, status_code=413)
                # Bound streamed/chunked requests as well as declared Content-Length.
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16_384:
                        return JSONResponse({"detail": "Request body too large."}, status_code=413)
                # Starlette's cached request must replay the bounded body downstream.
                request._body = bytes(body)  # pyright: ignore[reportPrivateUsage]
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        # Pydantic's default response echoes input, including submitted passwords.
        return JSONResponse({"detail": "Invalid request."}, status_code=422)

    @application.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/session")
    def get_session(request: Request) -> dict[str, Any]:
        return session_response(get_runtime().auth.verify(request.cookies.get(COOKIE_NAME)))

    @application.post("/api/login")
    def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        current = get_runtime()
        # Use the socket peer, never an arbitrary client-supplied forwarding header.
        if not current.limiter.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(
                429, "Too many login attempts. Try again later.", headers={"Retry-After": "300"}
            )
        if not current.auth.credentials_valid(body.username, body.password):
            raise HTTPException(401, "Invalid username or password.")
        token, payload = current.auth.issue()
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            secure=current.settings.cookie_secure,
            samesite="strict",
            max_age=current.settings.session_seconds,
            path="/",
        )
        return session_response(payload)

    @application.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, Any]:
        payload = session(request)
        csrf(request, payload)
        response.delete_cookie(
            COOKIE_NAME,
            path="/",
            secure=get_runtime().settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return session_response(None)

    @application.get("/api/dashboard")
    def dashboard(request: Request, refresh: Annotated[bool, Query()] = False) -> dict[str, Any]:
        session(request)
        current = get_runtime()
        if current.settings.mode == "demo":
            data = demo_dashboard()
            data["actions"] = [
                {
                    "id": "refresh-due",
                    "label": "Refresh due sources",
                    "description": "Synthetic demo",
                    "kind": "refresh_due",
                    "enabled": False,
                    "disabled_reason": "Synthetic demo actions are disabled.",
                    "requires_confirmation": True,
                }
            ]
            return data
        data = current.cache.get(refresh)
        actions, _, worker_ok = current.controls()
        data["actions"] = actions
        data["services"].append(
            service(
                "worker",
                "Host worker",
                "healthy" if worker_ok else "unavailable",
                "Worker available." if worker_ok else "Worker unavailable or stale.",
            )
        )
        try:
            data["jobs"] = [public_job(job) for job in current.store.list_jobs()]
        except Exception:
            data["notices"].append(
                {
                    "level": "warning",
                    "title": "Queue unavailable",
                    "body": "Job history is temporarily unavailable.",
                }
            )
        return data

    @application.post("/api/jobs", status_code=202)
    def enqueue(body: EnqueueRequest, request: Request) -> dict[str, Any]:
        payload = session(request)
        csrf(request, payload)
        current = get_runtime()
        if current.settings.mode == "demo":
            raise HTTPException(403, "Synthetic demo actions are disabled.")
        actions, profiles, _ = current.controls()
        profile = profiles.get(body.action_id)
        if profile is None:
            raise HTTPException(404, "Action not found.")
        action = next(item for item in actions if item["id"] == profile.id)
        # Idempotent HTTP retries should return the original job even if it is
        # now running. The store rechecks actor/action/profile identity atomically.
        try:
            existing = current.store.get_by_idempotency(body.idempotency_key)
            if existing is None and not action["enabled"]:
                raise HTTPException(409, action["disabled_reason"])
            job = current.store.enqueue(
                profile.id,
                payload["u"],
                body.idempotency_key,
                kind=profile.kind,
                profile_sha256=profile.fingerprint(),
            )
        except QueueConflict as error:
            raise HTTPException(409, str(error)) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Job queue is unavailable.") from None
        return {"job": public_job(job)}

    static_path = Path(__file__).parent / "static"
    if static_path.is_dir():
        application.mount("/static", StaticFiles(directory=static_path), name="static")

    @application.get("/")
    def index():
        path = static_path / "index.html"
        if not path.is_file():
            return Response("Dashboard assets are unavailable.", status_code=503)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    return application


app = create_app()

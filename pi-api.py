import os
import time
import uuid
import json
import threading
import re
import logging
from pathlib import Path
from typing import List, Optional, Union, Any

from curl_cffi import requests as cffi_requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel
import uvicorn
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

# ── config ──────────────────────────────────────────────────────────────

PORT = 8000
HOST = "127.0.0.1"
SHIM_API_KEY = ""
COOKIES_FILE = "cookies.json"
CF_REFRESH_SECS = 25 * 60

# ── rich logging ────────────────────────────────────────────────────────

console = Console(highlight=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(
            console=console,
            show_time=True,
            show_level=True,
            show_path=False,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            markup=True,
        )
    ],
)
log = logging.getLogger("pi-api")

# ── constants ───────────────────────────────────────────────────────────

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)
CONV_RE = re.compile(r"\[pi-conv:([A-Za-z0-9_-]+)\]")
AUTH_COOKIE_NAMES = {
    "__Host-session",
    "__Secure-pi-auth-state",
    "__Secure-pi-session",
}


def _error_response(status: int, message: str, etype: str = "invalid_request_error"):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": etype,
                "param": None,
                "code": None,
            }
        },
    )


# ── cookie manager ─────────────────────────────────────────────────────


class CookieManager:
    def __init__(self):
        self.cookies_file = Path(COOKIES_FILE)
        if not self.cookies_file.exists():
            console.print(
                Panel.fit(
                    "[bold red]cookies.json not found[/]\n\n"
                    "[dim]Export it from pi.ai using Cookie-Editor extension:[/]\n"
                    "[dim]1. Install Cookie-Editor browser extension[/]\n"
                    "[dim]2. Go to https://pi.ai and log in[/]\n"
                    "[dim]3. Click Cookie-Editor → Export → paste into cookies.json[/]",
                    border_style="red",
                    title="[bold red] Setup Required [/]",
                )
            )
            raise SystemExit(1)

        self.session = cffi_requests.Session(impersonate="chrome124")
        self._cf_at = 0
        self._lock = threading.Lock()
        self._load()
        threading.Thread(target=self._watch, daemon=True).start()

    def _load(self):
        try:
            raw = json.loads(self.cookies_file.read_text())
        except json.JSONDecodeError as e:
            log.error("[bold red]cookies.json is not valid JSON:[/] %s", e)
            raise SystemExit(1)

        if isinstance(raw, list):
            all_cookies = {
                c["name"]: c["value"]
                for c in raw
                if isinstance(c, dict) and "name" in c and "value" in c
            }
        elif isinstance(raw, dict):
            all_cookies = raw
        else:
            log.error("cookies.json must be a JSON array or object")
            raise SystemExit(1)

        auth = {}
        for name in AUTH_COOKIE_NAMES:
            val = all_cookies.get(name)
            if val:
                auth[name] = val
            elif name == "__Secure-pi-auth-state":
                auth[name] = "1"

        if not auth.get("__Host-session"):
            console.print(
                Panel.fit(
                    "[bold red]__Host-session cookie not found[/]\n\n"
                    "[dim]Make sure you're logged into pi.ai before exporting cookies.[/]",
                    border_style="red",
                    title="[bold red] Missing Cookie [/]",
                )
            )
            raise SystemExit(1)

        self.session.cookies.update(auth)
        log.info(
            "[bold green]✓[/] loaded [bold]%d[/] auth cookies from [bold]%s[/]",
            len(auth),
            self.cookies_file,
        )

    def _mint_cf(self):
        try:
            self.session.get("https://pi.ai/", headers={"Referer": "https://pi.ai/"})
            log.debug("[dim]cf_bm minted[/]")
        except Exception:
            pass

    def _watch(self):
        while True:
            time.sleep(CF_REFRESH_SECS)
            with self._lock:
                self._mint_cf()
                self._cf_at = time.time()

    def ensure(self):
        with self._lock:
            if time.time() - self._cf_at > CF_REFRESH_SECS:
                self._mint_cf()
                self._cf_at = time.time()


# ── pi client ──────────────────────────────────────────────────────────


class PiClient:
    BASE = "https://pi.ai"

    def __init__(self, cm: CookieManager):
        self.cm = cm
        self.eq_distinct = str(uuid.uuid4())
        self.eq_session = str(uuid.uuid4())

    @property
    def s(self):
        return self.cm.session

    def _headers(self, *, ver=None, ref=None, stream=False):
        h = {
            "User-Agent": UA,
            "Origin": self.BASE,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
            "Referer": ref or f"{self.BASE}/talk",
            "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        if ver:
            h["X-Api-Version"] = str(ver)
        return h

    def create_conversation(self, opener="Hi!"):
        self.cm.ensure()
        try:
            r = self.s.post(
                f"{self.BASE}/api/conversations",
                headers=self._headers(ver=2, ref=f"{self.BASE}/talk"),
                json={"aiOpener": opener},
                timeout=30,
            )
        except cffi_requests.RequestsError as e:
            log.error("[bold red]✗[/] connection failed: %s", e)
            raise RuntimeError(f"connection failed: {e}")

        if r.status_code in (401, 403):
            log.error(
                "[bold red]✗[/] auth rejected [bold](%d)[/] — re-export cookies from pi.ai",
                r.status_code,
            )
            raise RuntimeError("pi.ai rejected the session — re-export cookies.json")

        if r.status_code != 200:
            log.error(
                "[bold red]✗[/] create_conversation [bold]%d[/]: %s",
                r.status_code,
                r.text[:200],
            )
            raise RuntimeError(f"pi.ai returned {r.status_code}")

        try:
            sid = r.json()["sid"]
        except (KeyError, json.JSONDecodeError):
            log.error("[bold red]✗[/] unexpected response: %s", r.text[:200])
            raise RuntimeError("unexpected response from pi.ai")

        log.info("[bold cyan]✓[/] conversation [bold]%s[/] created", sid)
        return sid

    def stream(self, text, conv_id, prev=""):
        body = {
            "text": text,
            "conversation": conv_id,
            "eqDistinctId": self.eq_distinct,
            "eqSessionId": self.eq_session,
            "clientId": str(uuid.uuid4()),
            "tempChat": False,
            "previousConversation": prev,
        }
        self.cm.ensure()
        try:
            r = self.s.post(
                f"{self.BASE}/api/v2/chat",
                headers=self._headers(
                    ver=5,
                    ref=f"{self.BASE}/talk/{conv_id}",
                    stream=True,
                ),
                json=body,
                stream=True,
                timeout=180,
            )
        except cffi_requests.RequestsError as e:
            log.error("[bold red]✗[/] stream connection failed: %s", e)
            return

        if r.status_code in (401, 403):
            log.error(
                "[bold red]✗[/] stream auth rejected [bold](%d)[/] — re-export cookies",
                r.status_code,
            )
            return
        if r.status_code != 200:
            log.error(
                "[bold red]✗[/] chat [bold]%d[/] (conv=%s)", r.status_code, conv_id[:12]
            )
            try:
                log.error("  [dim]resp:[/] %.300s", r.text)
            except Exception:
                log.error("  [dim]resp(raw):[/] %r", r.content[:300])
            return

        ev = ""
        for chunk in r.iter_content(chunk_size=None):
            if not chunk:
                continue
            for line in chunk.decode("utf-8", "replace").split("\n"):
                line = line.rstrip("\r")
                if not line:
                    ev = ""
                    continue
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:") and ev == "partial":
                    try:
                        d = json.loads(line[5:].strip())
                        if d.get("text"):
                            yield d["text"]
                    except json.JSONDecodeError:
                        pass


# ── init ───────────────────────────────────────────────────────────────

cm = CookieManager()
pi = PiClient(cm)
app = FastAPI(title="Pi API")


# ── cors ───────────────────────────────────────────────────────────────


@app.middleware("http")
async def cors(request, call_next):
    origin = request.headers.get("origin")
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin or "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": request.headers.get(
                    "access-control-request-headers", "*"
                ),
                "Access-Control-Allow-Private-Network": "true",
                "Access-Control-Max-Age": "600",
            },
        )
    resp = await call_next(request)
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        resp.headers["Vary"] = "Origin"
    return resp


# ── models ─────────────────────────────────────────────────────────────


class Message(BaseModel):
    role: str
    content: Union[str, List[Any]]


class ChatRequest(BaseModel):
    model: str = "pi"
    messages: List[Message]
    stream: bool = False
    temperature: Optional[float] = None


# ── helpers ────────────────────────────────────────────────────────────


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content) if content else ""


def _check_auth(authorization: str = Header(None)):
    if SHIM_API_KEY and authorization != f"Bearer {SHIM_API_KEY}":
        raise HTTPException(401, "invalid api key")


def _extract_conv_id(msgs: List[Message]) -> Optional[str]:
    for m in reversed(msgs):
        if m.role == "assistant":
            hits = CONV_RE.findall(_content_to_text(m.content))
            if hits:
                return hits[-1]
    return None


def _strip_tags(text) -> str:
    return CONV_RE.sub("", _content_to_text(text)).strip()


def _last_user_msg(msgs: List[Message]) -> str:
    for m in reversed(msgs):
        if m.role == "user":
            return _strip_tags(m.content)
    return _strip_tags(msgs[-1].content) if msgs else ""


def _sse_chunk(cid, ts, model, delta, finish=None):
    return json.dumps(
        {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": ts,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": delta} if delta else {},
                    "finish_reason": finish,
                }
            ],
        }
    )


# ── routes ─────────────────────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def completions(req: ChatRequest, authorization: str = Header(None)):
    _check_auth(authorization)

    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    ts = int(time.time())

    # validate
    if not req.messages:
        log.warning("[bold yellow]⚠[/] empty messages array")
        return _error_response(400, "messages array is empty")

    prompt = _last_user_msg(req.messages)
    if not prompt:
        log.warning("[bold yellow]⚠[/] no user message content found")
        return _error_response(400, "last user message has no text content")

    if len(prompt) > 4000:
        log.warning(
            "[bold yellow]⚠[/] prompt too long: [bold]%d[/] chars (max [bold]%d[/])",
            len(prompt),
            4000,
        )
        return _error_response(
            400,
            f"prompt too long ({len(prompt)} chars, max {4000})",
        )

    conv_id = _extract_conv_id(req.messages)

    if conv_id:
        log.info(
            "[bold blue]→[/] reuse conv [bold]%s[/]  prompt=[dim]%s[/]%s  stream=%s",
            conv_id[:12],
            prompt[:60],
            "..." if len(prompt) > 60 else "",
            req.stream,
        )
        prev = ""
    else:
        log.info(
            "[bold blue]→[/] new conversation  prompt=[dim]%s[/]%s  stream=%s",
            prompt[:60],
            "..." if len(prompt) > 60 else "",
            req.stream,
        )
        try:
            conv_id = pi.create_conversation()
            time.sleep(1)
        except RuntimeError as e:
            log.error("[bold red]✗[/] %s", e)
            return _error_response(502, str(e), "api_error")
        except Exception as e:
            log.error("[bold red]✗[/] unexpected: %s", e)
            return _error_response(
                500, f"failed to create conversation: {e}", "server_error"
            )
        prev = ""

    suffix = f"\n\n[pi-conv:{conv_id}]"

    if req.stream:

        async def gen():
            got_text = False
            try:
                for delta in pi.stream(prompt, conv_id, prev):
                    got_text = True
                    yield f"data: {_sse_chunk(cid, ts, req.model, delta)}\n\n"
            except Exception as e:
                err_msg = "\n\n[error: {}]".format(e)
                yield f"data: {_sse_chunk(cid, ts, req.model, err_msg)}\n\n"
            if not got_text:
                err_msg = "\n\n[error: pi.ai returned no response -- check if cookies expired]"
                yield f"data: {_sse_chunk(cid, ts, req.model, err_msg)}\n\n"
                log.error(
                    "[bold red]✗[/] no response from pi.ai (conv=%s)", conv_id[:12]
                )
            else:
                log.info(
                    "[bold green]✓[/] streamed [bold]%d[/] chars  conv=[bold]%s[/]",
                    len(suffix),
                    conv_id[:12],
                )
            yield f"data: {_sse_chunk(cid, ts, req.model, suffix)}\n\n"
            yield f"data: {_sse_chunk(cid, ts, req.model, '', 'stop')}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        parts = list(pi.stream(prompt, conv_id, prev))
        full = "".join(parts)
        if not full:
            log.error(
                "[bold red]✗[/] empty response from pi.ai (conv=%s)", conv_id[:12]
            )
            return _error_response(
                502,
                "pi.ai returned no response -- cookies may have expired",
                "api_error",
            )
    except Exception as e:
        log.error("[bold red]✗[/] stream error: %s", e)
        return _error_response(502, f"pi.ai error: {e}", "api_error")

    full += suffix
    log.info(
        "[bold green]✓[/] response [bold]%d[/] chars  conv=[bold]%s[/]",
        len(full),
        conv_id[:12],
    )
    return JSONResponse(
        {
            "id": cid,
            "object": "chat.completion",
            "created": ts,
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": full},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    )


@app.get("/v1/models")
async def models(authorization: str = Header(None)):
    _check_auth(authorization)
    return {
        "object": "list",
        "data": [
            {
                "id": "pi",
                "object": "model",
                "created": 0,
                "owned_by": "inflection",
            }
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "cookies": len(cm.session.cookies)}


# ── entry ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Pi API[/] [dim]— OpenAI-compatible endpoint for pi.ai[/]\n\n"
            f"  [dim]Port       [/] [bold]{PORT}[/]\n"
            f"  [dim]Auth       [/] {'[bold green]enabled[/]' if SHIM_API_KEY else '[dim]disabled[/]'}\n"
            f"  [dim]Cookies    [/] [bold]{COOKIES_FILE}[/]\n"
            f"  [dim]Max prompt [/] [bold]{4000:,}[/] chars",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

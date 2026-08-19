"""轻量 API 认证中间件。

默认关闭以保持现有本机开发流程兼容；生产或局域网部署时通过
PAPER_WRITER_AUTH_REQUIRED=true 和 PAPER_WRITER_AUTH_TOKEN 启用。
"""

from __future__ import annotations

import hmac

from fastapi import Request
from starlette.responses import JSONResponse, Response


async def auth_middleware(request: Request, call_next, *, required: bool, token: str) -> Response:
    """Protect API routes with a bearer token when explicitly enabled.

    OPTIONS is intentionally passed through so browser CORS preflight can complete.
    Non-API routes (docs/static health pages) remain public and do not expose task data.
    """
    if not required or request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    # EventSource 和普通浏览器下载无法自定义 Authorization 头；仅对这两类
    # 固定只读/流式路径接受查询参数，普通 API 始终要求 Bearer Header。
    if not supplied and request.url.path.startswith(("/api/generate/stream/", "/api/download/", "/api/format/download/")):
        supplied = request.query_params.get("auth_token", "")
        scheme = "bearer"
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, token):
        return JSONResponse(
            status_code=401,
            content={"detail": "需要有效的 Bearer Token。"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


def parse_cors_origins(value: str) -> list[str]:
    """Parse a comma-separated CORS allowlist and ignore empty entries."""
    return [origin.strip() for origin in value.split(",") if origin.strip()]

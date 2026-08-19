import asyncio
from types import SimpleNamespace

from starlette.responses import Response

from app.auth import auth_middleware, parse_cors_origins


def run_auth(
    headers,
    *,
    path="/api/models",
    query_params=None,
    required=True,
    token="secret",
):
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path=path),
        headers=headers,
        query_params=query_params or {},
    )

    async def call_next(_request):
        return Response("ok", status_code=200)

    return asyncio.run(auth_middleware(request, call_next, required=required, token=token))


def test_cors_origins_are_trimmed_and_empty_values_removed():
    assert parse_cors_origins(" http://localhost:5173, ,http://127.0.0.1:5173 ") == [
        "http://localhost:5173", "http://127.0.0.1:5173"
    ]


def test_auth_is_opt_in():
    response = run_auth({}, required=False)
    assert response.status_code == 200


def test_api_rejects_missing_or_invalid_bearer_token():
    assert run_auth({}).status_code == 401
    assert run_auth({"authorization": "Bearer wrong"}).status_code == 401


def test_api_accepts_valid_bearer_token():
    response = run_auth({"authorization": "Bearer secret"})
    assert response.status_code == 200


def test_sse_and_download_paths_accept_valid_query_token_only():
    assert run_auth(
        {},
        path="/api/generate/stream/task-1",
        query_params={"auth_token": "secret"},
    ).status_code == 200
    assert run_auth(
        {},
        path="/api/download/task-1",
        query_params={"auth_token": "secret"},
    ).status_code == 200
    assert run_auth(
        {},
        path="/api/models",
        query_params={"auth_token": "secret"},
    ).status_code == 401


def test_non_api_routes_remain_public_when_auth_enabled():
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/docs"),
        headers={},
        query_params={},
    )

    async def call_next(_request):
        return Response("ok", status_code=200)

    response = asyncio.run(auth_middleware(request, call_next, required=True, token="secret"))
    assert response.status_code == 200

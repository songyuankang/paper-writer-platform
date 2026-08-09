"""AI 模型配置：CRUD、掩码、默认模型、测试连接、生成模型解析。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.crypto_utils import decrypt_secret, encrypt_secret
from app.db import get_conn
from app.models.generate import GenerateRequest
from app.models.model_config import ModelConfigCreate, ModelConfigUpdate
from app.services import deepseek


@dataclass(frozen=True)
class ModelRuntime:
    """AI 调用的统一模型配置。"""

    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_key(api_key: str) -> str:
    if len(api_key) <= 6:
        return "******"
    return "******" + api_key[-6:]


def _decrypt(row: dict) -> dict:
    row = dict(row)
    row["api_key"] = decrypt_secret(row["api_key"])
    return row


def _public(row: dict, include_key: bool = False) -> dict:
    row = dict(row)
    plain = decrypt_secret(row["api_key"])
    row["api_key_masked"] = mask_key(plain)
    row["has_api_key"] = bool(plain)
    row["is_default"] = bool(row["is_default"])
    row["enabled"] = bool(row["enabled"])
    if include_key:
        row["api_key"] = plain
    else:
        del row["api_key"]
    return row


def list_models() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM model_configs "
            "ORDER BY is_default DESC, created_at ASC").fetchall()
    return [_public(dict(r)) for r in rows]


def get_model(model_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM model_configs WHERE id = ?", (model_id,)).fetchone()
    return _decrypt(dict(row)) if row else None


def _get_raw(model_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM model_configs WHERE id = ?", (model_id,)).fetchone()
    return dict(row) if row else None


def create_model(data: ModelConfigCreate) -> dict:
    model_id = uuid.uuid4().hex
    now = _now()
    with get_conn() as conn:
        if data.is_default:
            conn.execute("UPDATE model_configs SET is_default = 0")
        conn.execute(
            """
            INSERT INTO model_configs
                (id, name, provider, base_url, api_key, model,
                 is_default, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (model_id, data.name, data.provider, data.base_url,
             encrypt_secret(data.api_key), data.model,
             int(data.is_default), int(data.enabled), now, now),
        )
    return _public(_get_raw(model_id), include_key=True)


def update_model(model_id: str, data: ModelConfigUpdate) -> dict | None:
    existing = get_model(model_id)
    if existing is None:
        return None
    fields = {
        "name": data.name, "provider": data.provider,
        "base_url": data.base_url, "model": data.model,
        "is_default": data.is_default, "enabled": data.enabled,
    }
    sets: list[str] = []
    values: list = []
    for key, value in fields.items():
        if value is not None:
            sets.append(f"{key} = ?")
            values.append(int(value) if key in ("is_default", "enabled") else value)
    if data.api_key is not None:
        sets.append("api_key = ?")
        values.append(encrypt_secret(data.api_key))
    if data.is_default:
        with get_conn() as conn:
            conn.execute("UPDATE model_configs SET is_default = 0")
    sets.append("updated_at = ?")
    values.append(_now())
    with get_conn() as conn:
        conn.execute(
            f"UPDATE model_configs SET {', '.join(sets)} WHERE id = ?",
            values + [model_id],
        )
    return _public(_get_raw(model_id))


def delete_model(model_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM model_configs WHERE id = ?", (model_id,))
        return cur.rowcount > 0


def set_default(model_id: str) -> bool:
    existing = get_model(model_id)
    if existing is None:
        return False
    with get_conn() as conn:
        conn.execute("UPDATE model_configs SET is_default = 0")
        conn.execute(
            "UPDATE model_configs SET is_default = 1, updated_at = ? "
            "WHERE id = ?", (_now(), model_id))
    return True


def _to_runtime(cfg: dict) -> ModelRuntime:
    return ModelRuntime(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        model=cfg["model"],
        temperature=settings.deepseek_temperature,
        max_tokens=settings.deepseek_max_tokens,
    )


def resolve_model(model_id: str | None = None,
                  task_dir: Path | None = None) -> ModelRuntime | None:
    """统一解析 AI 模型：指定 id → 任务原模型 → 默认启用模型 → .env。"""
    if model_id:
        cfg = get_model(model_id)
        if cfg and cfg["enabled"]:
            return _to_runtime(cfg)
    if task_dir is not None:
        req_path = task_dir / "request.json"
        try:
            req = GenerateRequest.model_validate_json(
                req_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - request.json 缺失或损坏时继续降级
            req = None
        if req is not None and req.model_id:
            cfg = get_model(req.model_id)
            if cfg and cfg["enabled"]:
                return _to_runtime(cfg)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM model_configs WHERE enabled = 1 "
            "ORDER BY is_default DESC, created_at ASC LIMIT 1").fetchone()
    if row is not None:
        return _to_runtime(_decrypt(dict(row)))
    if settings.deepseek_api_key and settings.deepseek_base_url and settings.deepseek_model:
        return ModelRuntime(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            temperature=settings.deepseek_temperature,
            max_tokens=settings.deepseek_max_tokens,
        )
    return None


def test_connection(payload: ModelTestRequest) -> dict:
    """测试连接：使用已保存模型或临时参数调用 OpenAI 兼容接口。"""
    base_url = payload.base_url
    api_key = payload.api_key
    model = payload.model
    if payload.id:
        cfg = get_model(payload.id)
        if cfg is None:
            raise ValueError("模型不存在")
        base_url = cfg["base_url"]
        api_key = cfg["api_key"]
        model = cfg["model"]
    if not (base_url and api_key and model):
        raise ValueError("缺少 base_url / api_key / model")
    deepseek.chat_with(
        base_url=base_url, api_key=api_key, model=model,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1, timeout=180)
    return {"ok": True, "message": "连接成功，模型可用"}

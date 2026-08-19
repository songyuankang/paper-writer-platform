from pathlib import Path

from app.api import models as models_api
from app.config import settings
from app.db import get_conn, init_db
from app.models.model_config import ModelConfigCreate, ModelConfigUpdate
from app.services import model_service


def _assert_public_model(record: dict, secret: str) -> None:
    assert "api_key" not in record
    assert secret not in record.values()
    assert record["has_api_key"] is True
    assert record["api_key_masked"].endswith(secret[-6:])


def test_model_config_responses_never_expose_plaintext_api_key(tmp_path, monkeypatch):
    db_path = Path(tmp_path) / "history.db"
    monkeypatch.setattr(settings, "db_path", db_path)
    init_db()

    first_secret = "sk-first-secret-123456"
    created = models_api.create_model(
        ModelConfigCreate(
            name="脱敏测试模型",
            provider="OpenAI Compatible",
            base_url="https://example.invalid/v1",
            api_key=first_secret,
            model="test-model",
        )
    )
    _assert_public_model(created, first_secret)

    # 数据库保留加密值，服务端运行时解析仍能取得明文用于真实请求。
    with get_conn() as conn:
        stored = conn.execute(
            "SELECT api_key FROM model_configs WHERE id = ?", (created["id"],)
        ).fetchone()["api_key"]
    assert stored != first_secret
    assert model_service.get_model(created["id"])["api_key"] == first_secret

    listed = models_api.list_models()["models"]
    assert len(listed) == 1
    _assert_public_model(listed[0], first_secret)

    second_secret = "sk-second-secret-654321"
    updated = models_api.update_model(
        created["id"],
        ModelConfigUpdate(api_key=second_secret),
    )
    _assert_public_model(updated, second_secret)
    assert model_service.get_model(created["id"])["api_key"] == second_secret

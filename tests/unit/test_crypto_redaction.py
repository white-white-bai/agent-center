from app.core.crypto import decrypt, encrypt
from app.core.redaction import redact, redact_text


def test_encrypt_roundtrip() -> None:
    token = encrypt("super-secret-token")

    assert token != "super-secret-token"
    assert decrypt(token) == "super-secret-token"


def test_encrypt_is_randomized() -> None:
    assert encrypt("same") != encrypt("same")


def test_redact_text_masks_id_phone_and_keys() -> None:
    text = "身份证 320402199001011234 电话 13800138000 key sk-abcdefgh12345"

    masked = redact_text(text)

    assert "320402199001011234" not in masked
    assert "13800138000" not in masked
    assert "sk-abcdefgh12345" not in masked


def test_redact_masks_secret_fields_recursively() -> None:
    payload = {
        "user": "u1",
        "authorization": "Bearer abc",
        "nested": {"password": "pwd", "phone": "13800138000"},
        "list": [{"token": "t"}],
    }

    masked = redact(payload)

    assert masked["authorization"] == "***"
    assert masked["nested"]["password"] == "***"
    assert masked["nested"]["phone"] == "[PHONE]"
    assert masked["list"][0]["token"] == "***"


async def test_credential_api_stores_ciphertext(async_client, db_session) -> None:
    from sqlalchemy import select

    from app.domain.tool.models import ToolCredential

    headers = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}
    created = await async_client.post(
        "/api/v1/admin/tools/matter.submit/credentials",
        json={"name": "api_key", "value": "sk-real-secret-value"},
        headers=headers,
    )

    assert created.status_code == 200
    assert created.json()["data"]["name"] == "api_key"

    listed = await async_client.get(
        "/api/v1/admin/tools/matter.submit/credentials", headers=headers
    )
    assert listed.json()["data"][0]["name"] == "api_key"
    assert "value" not in listed.json()["data"][0]

    stored = (await db_session.execute(select(ToolCredential))).scalars().all()
    assert stored[0].ciphertext != "sk-real-secret-value"

    other_tenant = await async_client.get(
        "/api/v1/admin/tools/matter.submit/credentials",
        headers={"X-Tenant-Id": "t2", "X-User-Id": "admin2", "X-Roles": "admin"},
    )
    assert other_tenant.json()["data"] == []

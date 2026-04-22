"""Тесты шифрования/дешифрования куков (pure unit, без БД)."""
import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services.cookie_service import _strip_transient_cookies, decrypt, encrypt


# --- _strip_transient_cookies ---

def test_strip_keeps_stable_cookies() -> None:
    """WBTokenV3, wbx-validation-key, x-supplier-id-external — оставляем."""
    raw = "WBTokenV3=abc; wbx-validation-key=def; x-supplier-id-external=xyz"
    assert _strip_transient_cookies(raw) == raw


def test_strip_removes_cloudflare_anti_bot() -> None:
    """cfidsw-wb (Cloudflare) и __zzatw-wb — динамические, удаляем."""
    raw = "WBTokenV3=abc; cfidsw-wb=ROTATING; __zzatw-wb=ALSO_ROTATING; x-supplier-id-external=xyz"
    result = _strip_transient_cookies(raw)
    assert "cfidsw-wb" not in result
    assert "__zzatw-wb" not in result
    assert "WBTokenV3=abc" in result
    assert "x-supplier-id-external=xyz" in result


def test_strip_removes_analytics_cookies() -> None:
    raw = "_ga=junk; _wbauid=junk; WBTokenV3=keep"
    result = _strip_transient_cookies(raw)
    assert "WBTokenV3=keep" in result
    assert "_ga=" not in result
    assert "_wbauid=" not in result


def test_strip_handles_empty_and_malformed() -> None:
    assert _strip_transient_cookies("") == ""
    assert _strip_transient_cookies(";  ; nokeyvalue; key=val") == "key=val"


# --- encrypt/decrypt ---


def test_encrypt_decrypt_roundtrip() -> None:
    original = "WBTokenV3=abc123; cfidsw-wb=xyz789; other=value"
    encrypted = encrypt(original)

    assert encrypted != original            # зашифровано
    assert decrypt(encrypted) == original   # и обратно


def test_encrypt_produces_different_ciphertext_each_time() -> None:
    """Fernet использует случайный IV — два вызова дают разный шифртекст."""
    value = "same_cookie_string"
    assert encrypt(value) != encrypt(value)


def test_decrypt_wrong_key_raises_invalid_token() -> None:
    """Попытка расшифровать другим ключом → InvalidToken."""
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()

    f1, f2 = Fernet(key1), Fernet(key2)
    encrypted = f1.encrypt(b"secret_cookie").decode()

    with pytest.raises(InvalidToken):
        f2.decrypt(encrypted.encode())


def test_encrypt_empty_string() -> None:
    """Пустая строка шифруется и дешифруется без ошибок."""
    assert decrypt(encrypt("")) == ""

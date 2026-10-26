import pytest
from cryptography.exceptions import InvalidTag

from oa_agent.config.crypto import Cipher, key_hint, mask_display
from oa_agent.ids import new_audit_id, new_run_id, new_thread_id
from oa_agent.kv import MemoryKV
from oa_agent.observability.redact import redact


def test_redact_common_secrets():
    text = (
        "Authorization: Bearer abcdefghijklmn mysql+pymysql://u:pa55@h/db api_key=sk-123456789 "
        "身份证 110101199003077777 卡 6222020200112233445 手机 13812345678 发票号码:12345678"
    )
    out = redact(text)
    for leaked in ("abcdefghijklmn", "pa55", "sk-123456789", "110101199003077777", "6222020200112233445",
                   "13812345678", "12345678"):
        assert leaked not in out, leaked


def test_redact_secrets_keeps_personal_info():
    from oa_agent.observability.redact import redact_secrets

    out = redact_secrets("手机 13812345678 身份证 110101199003077777 Authorization: Bearer abcdefgh12345 sk-abcdefgh1234")
    assert "13812345678" in out and "110101199003077777" in out
    assert "abcdefgh12345" not in out and "sk-abcdefgh1234" not in out
    assert not redact_secrets("a" * 5000).endswith("…[截断]")


def test_redact_truncates():
    assert redact("a" * 5000).endswith("…[截断]")


def test_cipher_roundtrip_and_aad_binding():
    c = Cipher(b"k" * 32)
    nonce, ct = c.encrypt("hello", "a")
    assert c.decrypt(nonce, ct, "a") == "hello"
    with pytest.raises(InvalidTag):
        c.decrypt(nonce, ct, "b")


def test_mask():
    assert key_hint("short") == ""
    assert mask_display(True, key_hint("abcdefgh1234")) == "已设置 · ****1234"
    assert mask_display(False, "") == "未设置"


def test_ids_prefix():
    assert new_run_id().startswith("run_") and new_thread_id().startswith("thr_")
    assert len(new_audit_id()) == 30


def test_memory_kv_set_nx_and_incr():
    kv = MemoryKV()
    assert kv.set_nx("k", "1", 5) is True
    assert kv.set_nx("k", "1", 5) is False
    assert kv.incr("c", 5) == 1 and kv.incr("c", 5) == 2

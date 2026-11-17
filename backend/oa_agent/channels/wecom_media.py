"""企业微信智能机器人长连接：媒体下载与 AES-256-CBC 解密。

协议：image/file/video 结构体含 url（约 5 分钟有效）与独立 aeskey；
加密为 AES-256-CBC，PKCS#7 填充，IV 取解码后 aeskey 的前 16 字节。
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

log = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = 30.0
_CHUNK_SAFE = 512 * 1024  # 企微分片上限（Base64 前）
_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?["\']?([^";]+)', re.I)


@dataclass(frozen=True)
class WeComMedia:
    """一条已解密的企微媒体。"""

    filename: str
    data: bytes
    media_kind: str  # image | file | video


def decrypt_aes_cbc(encrypted: bytes, aes_key: str) -> bytes:
    """按企微文档解密媒体字节。"""
    if not encrypted:
        raise ValueError("encrypted_data is empty")
    if not aes_key or not isinstance(aes_key, str):
        raise ValueError("aes_key must be a non-empty string")
    padded = aes_key + "=" * ((4 - len(aes_key) % 4) % 4)
    key = base64.b64decode(padded)
    iv = key[:16]
    block = 16
    rem = len(encrypted) % block
    if rem:
        encrypted = encrypted + b"\x00" * (block - rem)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    plain = decryptor.update(encrypted) + decryptor.finalize()
    if not plain:
        raise ValueError("decrypted data is empty")
    pad_len = plain[-1]
    if pad_len < 1 or pad_len > 32 or pad_len > len(plain):
        raise ValueError(f"invalid PKCS#7 padding: {pad_len}")
    if any(b != pad_len for b in plain[-pad_len:]):
        raise ValueError("invalid PKCS#7 padding bytes")
    return plain[:-pad_len]


def download_and_decrypt(url: str, aeskey: str, *, timeout: float = _DOWNLOAD_TIMEOUT,
                         transport: httpx.BaseTransport | None = None) -> tuple[bytes, str]:
    """下载加密媒体并解密；返回 (bytes, filename_hint)。"""
    if not url or not aeskey:
        raise ValueError("url/aeskey missing")
    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=True) as client:
        resp = client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"download HTTP {resp.status_code}")
    name = _filename_from_headers(resp.headers) or ""
    data = decrypt_aes_cbc(resp.content, aeskey)
    return data, name


def collect_media(body: dict, *, transport: httpx.BaseTransport | None = None) -> list[WeComMedia]:
    """从企微回调 body 收集可入库的图片/文件（视频暂不入库，与 Web 附件准入一致）。"""
    kind = body.get("msgtype")
    out: list[WeComMedia] = []
    if kind == "image":
        item = _one_media(body.get("image") or {}, default_name="image.jpg", media_kind="image",
                          transport=transport)
        if item:
            out.append(item)
    elif kind == "file":
        item = _one_media(body.get("file") or {}, default_name="file.bin", media_kind="file",
                          transport=transport)
        if item:
            out.append(item)
    elif kind == "mixed":
        items = (body.get("mixed") or {}).get("msg_item") or []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            mt = raw.get("msgtype")
            if mt == "image":
                item = _one_media(raw.get("image") or {}, default_name="image.jpg", media_kind="image",
                                  transport=transport)
            elif mt == "file":
                item = _one_media(raw.get("file") or {}, default_name="file.bin", media_kind="file",
                                  transport=transport)
            else:
                continue
            if item:
                out.append(item)
    return out


def _one_media(info: dict, *, default_name: str, media_kind: str,
               transport: httpx.BaseTransport | None) -> WeComMedia | None:
    url = str(info.get("url") or info.get("fileurl") or "").strip()
    aeskey = str(info.get("aeskey") or "").strip()
    if not url or not aeskey:
        return None
    try:
        data, hinted = download_and_decrypt(url, aeskey, transport=transport)
    except Exception:  # noqa: BLE001 —— 单条媒体失败时跳过，由上层决定是否提示
        log.exception("企微媒体下载/解密失败")
        return None
    name = (
        str(info.get("filename") or info.get("name") or "").strip()
        or hinted
        or default_name
    )
    name = name.replace("\\", "/").rsplit("/", 1)[-1] or default_name
    if media_kind == "image" and "." not in name:
        name = f"{name}.jpg"
    return WeComMedia(filename=name, data=data, media_kind=media_kind)


def _filename_from_headers(headers) -> str:
    cd = headers.get("content-disposition") or headers.get("Content-Disposition") or ""
    m = _FILENAME_RE.search(cd)
    if not m:
        return ""
    return unquote(m.group(1).strip().strip('"'))


def media_chunks(data: bytes, chunk_size: int = _CHUNK_SAFE) -> list[bytes]:
    """按企微上传分片大小切分。"""
    if chunk_size < 1:
        raise ValueError("chunk_size")
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)] or [b""]

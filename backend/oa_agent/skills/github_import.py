"""从公开 GitHub 仓库拉取 Skill 包目录。"""

from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from typing import Any

import httpx

from oa_agent.skills.parse import SkillMdError
from oa_agent.skills.pack_store import MAX_TOTAL_BYTES, _norm_rel

log = logging.getLogger(__name__)

GITHUB_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)"
    r"(?:/(?:tree|blob)/(?P<ref>[^/]+)(?:/(?P<subpath>.*))?)?/?$"
)
MAX_ZIP_BYTES = 30 * 1024 * 1024
TIMEOUT = httpx.Timeout(connect=15.0, read=90.0, write=30.0, pool=15.0)
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SEC = (1.0, 2.5, 5.0)


def parse_github_url(url: str) -> dict[str, str]:
    text = (url or "").strip()
    m = GITHUB_RE.fullmatch(text.split("?")[0].rstrip("/"))
    if not m:
        raise SkillMdError("仅支持 https://github.com/owner/repo[/tree/ref/path] 形式的公开地址")
    owner, repo = m.group("owner"), m.group("repo")
    if repo.endswith(".git"):
        repo = repo[:-4]
    ref = m.group("ref") or "main"
    subpath = (m.group("subpath") or "").strip("/")
    return {"owner": owner, "repo": repo, "ref": ref, "subpath": subpath, "url": text}


def _zipball_urls(owner: str, repo: str, ref: str) -> list[str]:
    return [
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/tags/{ref}",
        f"https://codeload.github.com/{owner}/{repo}/zip/{ref}",
    ]


def _network_error_message(exc: BaseException) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "连接 GitHub 超时，请检查网络或代理后重试"
    if isinstance(exc, httpx.ReadTimeout):
        return "下载 GitHub 仓库超时，请稍后重试或缩小 paths 范围"
    if isinstance(exc, httpx.ConnectError):
        return "无法连接 GitHub（网络不通或被拦截），请检查出网/代理后重试"
    if isinstance(exc, httpx.ProxyError):
        return "GitHub 代理错误，请检查 HTTP(S)_PROXY 配置后重试"
    if isinstance(exc, httpx.HTTPError):
        return f"访问 GitHub 网络异常：{type(exc).__name__}"
    return f"拉取失败：{type(exc).__name__}"


def fetch_repo_zip(owner: str, repo: str, ref: str, *, client: httpx.Client | None = None) -> bytes:
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    try:
        last_err = "无法下载仓库"
        urls = _zipball_urls(owner, repo, ref)
        for attempt in range(MAX_ATTEMPTS):
            for url in urls:
                try:
                    resp = http.get(url)
                except httpx.HTTPError as exc:
                    last_err = _network_error_message(exc)
                    log.warning("GitHub 下载失败 attempt=%s url=%s err=%s", attempt + 1, url, last_err)
                    continue
                if resp.status_code == 404:
                    last_err = f"仓库或分支不存在（{owner}/{repo}@{ref}）"
                    continue
                if resp.status_code in (429, 502, 503, 504):
                    last_err = f"GitHub 暂时不可用（HTTP {resp.status_code}），请稍后重试"
                    continue
                if resp.status_code >= 400:
                    last_err = f"GitHub 返回 HTTP {resp.status_code}"
                    continue
                data = resp.content
                if len(data) > MAX_ZIP_BYTES:
                    raise SkillMdError("仓库压缩包过大")
                return data
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)])
        raise SkillMdError(f"拉取 GitHub 失败：{last_err}")
    finally:
        if own:
            http.close()


def extract_skill_dirs(zip_bytes: bytes, *, subpath: str = "", only_paths: list[str] | None = None
                       ) -> list[tuple[str, dict[str, bytes]]]:
    """从 zip 中找出含 SKILL.md 的目录；返回 [(relative_dir, files)]。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise SkillMdError("GitHub 返回内容不是有效 zip") from exc
    names = zf.namelist()
    if not names:
        raise SkillMdError("仓库为空")
    root_prefix = names[0].split("/")[0] + "/"

    scopes: list[str] = []
    if only_paths:
        for p in only_paths:
            rel = p.strip("/").replace("\\", "/")
            if rel:
                scopes.append(f"{root_prefix}{rel}/")
    elif subpath:
        scopes.append(f"{root_prefix}{subpath.strip('/')}/")
    else:
        scopes.append(root_prefix)

    skill_files = [
        n for n in names
        if n.endswith("/SKILL.md") or n.endswith("/skill.md") or n == f"{root_prefix}SKILL.md"
    ]
    packs: list[tuple[str, dict[str, bytes]]] = []
    total = 0
    seen_dirs: set[str] = set()
    for skill_path in skill_files:
        if not any(skill_path.startswith(s) or skill_path == s.rstrip("/") + "/SKILL.md"
                   or skill_path == s.rstrip("/") + "/skill.md" for s in scopes):
            continue
        dir_prefix = skill_path.rsplit("/", 1)[0] + "/"
        if dir_prefix in seen_dirs:
            continue
        seen_dirs.add(dir_prefix)
        rel_dir = dir_prefix[len(root_prefix):].rstrip("/")
        files: dict[str, bytes] = {}
        for name in names:
            if not name.startswith(dir_prefix) or name.endswith("/"):
                continue
            rel = name[len(dir_prefix):]
            try:
                rel = _norm_rel(rel)
            except SkillMdError:
                continue
            data = zf.read(name)
            total += len(data)
            if total > MAX_TOTAL_BYTES * 2:
                raise SkillMdError("导入内容总体积过大")
            files[rel] = data
        if "SKILL.md" in files:
            packs.append((rel_dir or "skill", files))
    if not packs:
        raise SkillMdError("未找到含 SKILL.md 的目录（请检查 paths 或仓库结构）")
    return packs


def import_from_github(url: str, *, paths: list[str] | None = None,
                       client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """返回 [{dir, files, source_url}]。"""
    info = parse_github_url(url)
    only = paths
    sub = "" if only else info["subpath"]
    try:
        zip_bytes = fetch_repo_zip(info["owner"], info["repo"], info["ref"], client=client)
    except SkillMdError:
        raise
    except httpx.HTTPError as exc:
        raise SkillMdError(_network_error_message(exc)) from exc
    extracted = extract_skill_dirs(zip_bytes, subpath=sub, only_paths=only)
    return [{"dir": d, "files": f, "source_url": info["url"]} for d, f in extracted]

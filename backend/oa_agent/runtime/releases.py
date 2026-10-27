"""Workflow 配置版本与发布（设计 §8、"3 P5）"

- 版本状态：draft（唯一可改）→ validated（内容哈希被锁定）→ published（不可改）。改草稿内容即回"draft"
- 发布要求：状态为 validated 且内容哈希与校验时一致；回滚 = 新增一"rollback 发布记录指向历史已发布版本"
- 运行开始时绑定当时的发布（config_release_id），执行与恢复都用该发布的快照，发布新版本不影响执行中的运行"
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from oa_agent.db.models import AgentDefinition, ConfigRelease, LlmModel, WorkflowVersion
from oa_agent.db.types import utcnow
from oa_agent.ids import new_release_id, new_workflow_version_id
from oa_agent.executor.catalog import canonical_hash
from oa_agent.runtime.graphs import travel_query

log = logging.getLogger(__name__)

DRAFT, VALIDATED, PUBLISHED = "draft", "validated", "published"
PUBLISH, ROLLBACK = "publish", "rollback"

BASIC, DIALOG, MEMORY, OUTPUT = "基础", "对话与角色", "多轮对话与会话压缩", "工具串联与输出"
GROUPS = (BASIC, DIALOG, MEMORY, OUTPUT)

FIELDS = (
    {"key": "intent_mode", "group": BASIC, "label": "意图解析方式", "kind": "enum",
     "options": [{"value": "auto", "label": "自动（有可用模型时用模型，失败回退规则）"},
                 {"value": "rules", "label": "仅规则"}],
     "help": "自动：由模型理解员工的话、选择工具或直接回答；模型不可用或调用失败时退回内置规则（只认识行程报销的固定说法）"
             "仅规则：不调用模型，只能回答行程报销查询，其他问题回复帮助"},
    {"key": "llm_model_id", "group": BASIC, "label": "指定模型", "kind": "model",
     "help": "留空使用默认模型（带 intent 用途标签的优先，否则第一个启用的模型）。指定的模型被停用时发布校验不通过"},
    {"key": "list_default_limit", "group": BASIC, "label": "列表默认条数", "kind": "int", "min": 1, "max": 20,
     "unit": "", "help": "员工没说要看几条时，列表查询默认返回的条数；员工明确说了（如「最近 3 笔」）以员工为准，"
                         "且不超过 Tool 参数规则里的上限"},
    {"key": "on_upstream_error", "group": BASIC, "label": "上游故障处理", "kind": "enum",
     "options": [{"value": "fail", "label": "直接失败（提示员工稍后再试）"},
                 {"value": "handoff", "label": "转人工介入（管理员决定重试或终止）"}],
     "help": "office-api 超时、不可达或返回 5xx 时的处理。转人工后运行挂起，在「人工介入」页处理；"
             "业务校验失败（4xx）不会转人工，直接把业务系统的提示告诉员工"},
    {"key": "help_text", "group": BASIC, "label": "帮助回复", "kind": "text", "max": 2000,
     "help": "员工问「你能做什么」或问题无法处理时的回复。留空则按可用 Skill 的名称、说明和示例问题自动生成（推荐）；"
             "Skill 变化时自动更新）"},
    {"key": "chat_mode", "group": DIALOG, "label": "非查询问题（聊天模式）", "kind": "enum",
     "options": [{"value": "llm", "label": "由模型直接回答（日常聊天、通用问答）"},
                 {"value": "help", "label": "回复帮助文案"}],
     "help": "与查询无关的问题（打招呼、闲聊、常识、写作润色等）怎么处理。仅「自动」意图解析且有可用模型时生效；否则回复帮助"},
    {"key": "assistant_persona", "group": DIALOG, "label": "角色设定", "kind": "text", "max": 500,
     "default": travel_query.DEFAULT_PERSONA,
     "help": "提示词开头的身份描述，决定助手的自称和语气，如「你是 XX 公司的行政小助手『小 O』」。"
             "输出格式与安全规则（不编造业务数据、不代办业务、身份由系统注入）固定在代码中，这里无法修改。留空恢复默认"},
    {"key": "chat_instructions", "group": DIALOG, "label": "回答补充要求", "kind": "text", "max": 1000,
     "help": "追加给模型的回答要求，如语气、篇幅、可回答的范围（「只回答与工作相关的问题」）"
             "不能放宽「不编造业务数据、不代办业务」的限制，写了也不生效"},
    {"key": "history_turns", "group": MEMORY, "label": "多轮追问：带给模型的对话轮数", "kind": "int",
     "min": 0, "max": 30, "unit": "",
     "help": "模型能看到本会话最近几轮对话（1 轮 = 员工一句 + 助手一句），用来理解「那上个月的呢」「第一条的详情」这类追问。"
             "轮数越多理解越连贯，但每次调用的 Token 越多、越慢。0 = 每句话独立理解。"
             "查询结果在历史里只保留工具、条件和记录 ID，不含业务明细"},
    {"key": "history_message_chars", "group": MEMORY, "label": "每条历史消息的最大字数", "kind": "int",
     "min": 100, "max": 4000, "unit": "",
     "help": "带给模型的每条历史消息超过该字数时截断，防止一条长回复占满上下文"},
    {"key": "history_ref_ids", "group": MEMORY, "label": "查询摘要中保留的记录 ID ", "kind": "int",
     "min": 0, "max": 100, "unit": "",
     "help": "列表查询后，历史里按显示顺序记下前 N 条记录的 ID，员工说「第 3 条的详情」时模型据此选 ID。"
             "0 = 不记 ID（这类追问将无法理解）"},
    {"key": "history_compress", "group": MEMORY, "label": "超出轮数时压缩会话", "kind": "bool",
     "help": "对话超过上面的轮数后，更早的对话怎么处理。开启：按下面的方式压缩成「记忆」带给模型，"
             "员工很久之前提过的偏好、条件仍能被理解；关闭：直接丢弃，模型只看到最近几轮"},
    {"key": "history_compress_mode", "group": MEMORY, "label": "压缩方式", "kind": "enum",
     "options": [{"value": "truncate", "label": "截断压缩（不调用模型，零成本）"},
                 {"value": "summary", "label": "滚动摘要（模型改写摘要）"},
                 {"value": "facts", "label": "要点提取（模型提取关键事实）"}],
     "help": "截断压缩：每条旧消息只保留开头若干字，按时间顺序排列，超出记忆上限丢最早的；简单可靠、不额外花钱"
             "但长消息后半段会丢失。\n"
             "滚动摘要：每次有对话移出时，模型把「已有摘要 + 移出的对话」改写成一段新摘要；语义保留最好，"
             "但每轮多一次模型调用（增加约 1 秒和相应 Token）。\n"
             "要点提取：模型从移出的对话中提取偏好、查询条件、记录 ID、未完成的请求等要点并去重合并；"
             "最适合查询类助手，成本与滚动摘要相当。\n"
             "模型方式失败（未配置模型、调用失败、输出无效）时自动改用截断压缩，不影响回复"},
    {"key": "compress_memory_chars", "group": MEMORY, "label": "记忆最大字数", "kind": "int",
     "min": 200, "max": 4000, "unit": "",
     "help": "压缩后的记忆总长度上限，超出时丢弃最早的内容。记忆随每次模型调用一起发送，越长 Token 越多"},
    {"key": "compress_truncate_chars", "group": MEMORY, "label": "截断压缩：每条保留字数", "kind": "int",
     "min": 20, "max": 500, "unit": "", "help": "仅「截断压缩」使用：每条旧消息保留开头的字数"},
    {"key": "max_tool_steps", "group": OUTPUT, "label": "工具串联最大步数", "kind": "int",
     "min": 1, "max": 5, "unit": "",
     "help": "一个问题需要先用 A 再用 A 的结果查 B 时（如「我最近一笔报销的详情」），模型一次规划多个步骤，"
             "后面步骤的参数引用前面步骤的返回字段，由服务端取值（模型看不到任何返回数据）"
             "1 = 不串联，每次只调一个工具。步数越多越容易出现中途无数据而停止"},
    {"key": "max_table_rows", "group": OUTPUT, "label": "表格最多显示行数", "kind": "int",
     "min": 1, "max": 200, "unit": "",
     "help": "列表结果在回复里最多显示的行数；超出时提示「显示前 N 条」。企业微信单条消息有 20KB 上限，过多的行会被截断"},
    {"key": "chat_reply_max_chars", "group": OUTPUT, "label": "聊天回复最大字数", "kind": "int",
     "min": 200, "max": 20000, "unit": "",
     "help": "模型直接回答（非查询）时回复的最大字数，超出部分截掉。需要更长回答时同时调大模型的 max_tokens"},
    {"key": "stream_output", "group": OUTPUT, "label": "流式输出", "kind": "bool",
     "help": "开启后模型边生成边显示：网页对话逐字出现，企业微信按「企业微信流式刷新间隔」逐段刷新"
             "查询结果表格由系统生成，会一次性显示。关闭则等完整回复生成后一次显示"},
)
FIELD_MAP = {f["key"]: f for f in FIELDS}
# 旧版本配置里的字段：仍可校验通过，运行时忽略（可"Skill 改由「Skill 管理」决定）
LEGACY_KEYS = {"skill"}
# 最初版本就有的字段，校验要求必须出现；其余为后加字段，旧版本里没有时按默认值运"
REQUIRED_KEYS = {"intent_mode", "llm_model_id", "list_default_limit", "on_upstream_error", "help_text"}


class Release:
    __slots__ = ("release_id", "version_no", "config")

    def __init__(self, release_id: str | None, version_no: int | None, config: dict):
        self.release_id, self.version_no, self.config = release_id, version_no, config


class ReleaseError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def validate_content(db: Session, tenant_id: str, content: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(content, dict):
        return ["配置必须是对"]
    expected = set(travel_query.DEFAULT_CONFIG)
    unknown, missing = set(content) - expected - LEGACY_KEYS, REQUIRED_KEYS - set(content)
    if unknown:
        errors.append(f"未知字段：{sorted(unknown)}")
    if missing:
        errors.append(f"缺少字段：{sorted(missing)}")
    for f in FIELDS:
        if f["kind"] == "model" or (f["key"] not in content and f["key"] not in REQUIRED_KEYS):
            continue
        error = _field_error(f, content.get(f["key"]))
        if error:
            errors.append(error)
    model_id = content.get("llm_model_id")
    if model_id is not None:
        if not isinstance(model_id, int) or isinstance(model_id, bool):
            errors.append("指定模型必须是模型 ID 或留空")
        elif db.scalar(sa.select(LlmModel.id).where(LlmModel.tenant_id == tenant_id, LlmModel.id == model_id,
                                                    LlmModel.enabled.is_(True))) is None:
            errors.append(f"指定模型 {model_id} 不存在或未启用")
    return errors


def _field_error(f: dict, value) -> str | None:
    label, kind = f["label"], f["kind"]
    if kind == "enum":
        allowed = [o["value"] for o in f["options"]]
        return None if value in allowed else f"{label}只能是 {' / '.join(allowed)}"
    if kind == "bool":
        return None if isinstance(value, bool) else f"{label}必须是开或关"
    if kind == "int":
        ok = isinstance(value, int) and not isinstance(value, bool) and f["min"] <= value <= f["max"]
        return None if ok else f"{label}必须在 {f['min']}～{f['max']} 的整"
    if kind == "text":
        ok = isinstance(value, str) and len(value) <= f["max"]
        return None if ok else f"{label}必须是不超过 {f['max']} 字的文本"
    return None


def diff_content(old: dict | None, new: dict | None) -> list[dict]:
    old, new = old or {}, new or {}
    return [{"key": k, "old": old.get(k), "new": new.get(k)}
            for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]


class ReleaseService:
    def __init__(self, session_factory: Callable[[], Session], tenant_id: str):
        self._sf = session_factory
        self.tenant = tenant_id
        self.workflow_id = travel_query.WORKFLOW_ID
        self._lock = threading.Lock()
        self._current: Release | None = None
        self._by_id: dict[str, Release] = {}

    # ---- 启动 ----
    def seed(self) -> None:
        """首次启动：建 Agent 定义"v1 发布（代码默认配置），保证开箱即可对话"""
        with self._sf() as db, db.begin():
            if db.scalar(sa.select(AgentDefinition.id).where(AgentDefinition.tenant_id == self.tenant,
                                                             AgentDefinition.agent_id == travel_query.AGENT_ID)):
                return
            now = utcnow()
            db.add(AgentDefinition(tenant_id=self.tenant, agent_id=travel_query.AGENT_ID, name="OA 助手",
                                   workflow_id=self.workflow_id, created_at=now))
            content = dict(travel_query.DEFAULT_CONFIG)
            digest = canonical_hash(content)
            version = WorkflowVersion(version_id=new_workflow_version_id(), tenant_id=self.tenant,
                                      workflow_id=self.workflow_id, version_no=1, content_json=content,
                                      content_hash=digest, status=PUBLISHED, validated_hash=digest,
                                      validation_json={"ok": True, "errors": []}, created_by="system",
                                      updated_by="system", created_at=now, updated_at=now, published_at=now)
            db.add(version)
            db.add(ConfigRelease(release_id=new_release_id(), tenant_id=self.tenant, workflow_id=self.workflow_id,
                                 workflow_version_id=version.version_id, version_no=1, release_type=PUBLISH,
                                 reason="初始版本（代码默认配置）", released_by="system", released_at=now))

    # ---- 运行"----
    def current(self) -> Release:
        try:
            with self._sf() as db:
                row = db.execute(
                    sa.select(ConfigRelease, WorkflowVersion)
                    .join(WorkflowVersion, WorkflowVersion.version_id == ConfigRelease.workflow_version_id)
                    .where(ConfigRelease.tenant_id == self.tenant, ConfigRelease.workflow_id == self.workflow_id)
                    .order_by(ConfigRelease.id.desc()).limit(1)).first()
        except SQLAlchemyError:
            log.error("读取当前发布失败，沿用缓")
            row = None
            if self._current is not None:
                return self._current
        if row is None:
            return self._current or Release(None, None, dict(travel_query.DEFAULT_CONFIG))
        release, version = row
        result = Release(release.release_id, version.version_no, {**travel_query.DEFAULT_CONFIG,
                                                                   **version.content_json})
        with self._lock:
            self._current = result
            self._by_id[release.release_id] = result
        return result

    def get(self, release_id: str) -> Release:
        with self._lock:
            hit = self._by_id.get(release_id)
        if hit is not None:
            return hit
        with self._sf() as db:
            row = db.execute(
                sa.select(ConfigRelease, WorkflowVersion)
                .join(WorkflowVersion, WorkflowVersion.version_id == ConfigRelease.workflow_version_id)
                .where(ConfigRelease.release_id == release_id)).first()
        if row is None:
            raise ReleaseError(409, "RELEASE_NOT_FOUND", f"运行绑定的发布 {release_id} 不存在")
        release, version = row
        result = Release(release.release_id, version.version_no, {**travel_query.DEFAULT_CONFIG,
                                                                   **version.content_json})
        with self._lock:
            self._by_id[release_id] = result
        return result

    # ---- 管理 ----
    def draft(self, db: Session) -> WorkflowVersion | None:
        return db.scalar(sa.select(WorkflowVersion).where(
            WorkflowVersion.tenant_id == self.tenant, WorkflowVersion.workflow_id == self.workflow_id,
            WorkflowVersion.status.in_([DRAFT, VALIDATED])))

    def current_row(self, db: Session) -> tuple[ConfigRelease, WorkflowVersion] | None:
        row = db.execute(
            sa.select(ConfigRelease, WorkflowVersion)
            .join(WorkflowVersion, WorkflowVersion.version_id == ConfigRelease.workflow_version_id)
            .where(ConfigRelease.tenant_id == self.tenant, ConfigRelease.workflow_id == self.workflow_id)
            .order_by(ConfigRelease.id.desc()).limit(1)).first()
        return (row[0], row[1]) if row else None

    def save_draft(self, db: Session, content: dict, operator: str) -> WorkflowVersion:
        now = utcnow()
        digest = canonical_hash(content)
        draft = self.draft(db)
        if draft is None:
            draft = WorkflowVersion(version_id=new_workflow_version_id(), tenant_id=self.tenant,
                                    workflow_id=self.workflow_id, content_json=content, content_hash=digest,
                                    status=DRAFT, created_by=operator, updated_by=operator, created_at=now,
                                    updated_at=now)
            db.add(draft)
        elif draft.content_hash != digest:
            draft.content_json, draft.content_hash = content, digest
            draft.status, draft.validated_hash, draft.validation_json = DRAFT, None, None
            draft.updated_by, draft.updated_at = operator, now
        db.flush()
        return draft

    def validate_draft(self, db: Session, operator: str) -> WorkflowVersion:
        draft = self._require_draft(db)
        errors = validate_content(db, self.tenant, draft.content_json)
        draft.validation_json = {"ok": not errors, "errors": errors, "validated_at": utcnow().isoformat()}
        draft.status = DRAFT if errors else VALIDATED
        draft.validated_hash = None if errors else draft.content_hash
        draft.updated_by, draft.updated_at = operator, utcnow()
        db.flush()
        return draft

    def _require_draft(self, db: Session) -> WorkflowVersion:
        draft = self.draft(db)
        if draft is None:
            raise ReleaseError(404, "DRAFT_NOT_FOUND", "没有草稿")
        return draft

    def discard_draft(self, db: Session) -> None:
        db.delete(self._require_draft(db))

    def publish(self, db: Session, content_hash: str, reason: str, operator: str) -> ConfigRelease:
        draft = self._require_draft(db)
        if draft.status != VALIDATED or draft.validated_hash != draft.content_hash:
            raise ReleaseError(409, "NOT_VALIDATED", "草稿未通过校验（或校验后又被修改），不能发")
        if content_hash != draft.content_hash:
            raise ReleaseError(409, "DRAFT_CHANGED", "草稿内容与页面上看到的不一致，请刷新后再发")
        errors = validate_content(db, self.tenant, draft.content_json)  # 依赖（模"Skill）可能在校验后变"
        if errors:
            raise ReleaseError(409, "NOT_VALIDATED", "发布前复核失败：" + "".join(errors))
        now = utcnow()
        version_no = (db.scalar(sa.select(sa.func.max(WorkflowVersion.version_no)).where(
            WorkflowVersion.tenant_id == self.tenant, WorkflowVersion.workflow_id == self.workflow_id)) or 0) + 1
        draft.version_no, draft.status, draft.published_at = version_no, PUBLISHED, now
        draft.updated_by, draft.updated_at = operator, now
        return self._release(db, draft, PUBLISH, reason, operator)

    def rollback(self, db: Session, version_no: int, reason: str, operator: str) -> ConfigRelease:
        target = db.scalar(sa.select(WorkflowVersion).where(
            WorkflowVersion.tenant_id == self.tenant, WorkflowVersion.workflow_id == self.workflow_id,
            WorkflowVersion.version_no == version_no, WorkflowVersion.status == PUBLISHED))
        if target is None:
            raise ReleaseError(404, "VERSION_NOT_FOUND", f"已发布版本 v{version_no} 不存在")
        current = self.current_row(db)
        if current and current[1].version_id == target.version_id:
            raise ReleaseError(409, "ALREADY_CURRENT", f"v{version_no} 已是当前生效版本")
        errors = validate_content(db, self.tenant, target.content_json)
        if errors:
            raise ReleaseError(409, "NOT_VALIDATED", f"v{version_no} 的依赖已不可用：" + "".join(errors))
        return self._release(db, target, ROLLBACK, reason, operator)

    def _release(self, db: Session, version: WorkflowVersion, kind: str, reason: str,
                 operator: str) -> ConfigRelease:
        current = self.current_row(db)
        release = ConfigRelease(release_id=new_release_id(), tenant_id=self.tenant, workflow_id=self.workflow_id,
                                workflow_version_id=version.version_id, version_no=version.version_no,
                                release_type=kind, reason=reason, released_by=operator, released_at=utcnow(),
                                previous_release_id=current[0].release_id if current else None)
        db.add(release)
        db.flush()
        return release

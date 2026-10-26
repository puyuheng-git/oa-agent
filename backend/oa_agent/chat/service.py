"""运行编排：一次对话消"= 一次运行；转人工、恢复、终止、取消、重试也在这里收口"

身份只来自服务端会话：运行上下文（KV）只存会话引用，恢复/重试时重新加载并校验会话仍有效且属于同一员工"
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from oa_agent.auth import chat_launch
from oa_agent.auth.chat_launch import ChatSession
from oa_agent.chat import threads
from oa_agent.config.schema import GROUPS
from oa_agent.db.models import Run
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError
from oa_agent.ids import new_run_id
from oa_agent.integrations.office_api import OfficeApiClient, OfficeApiError, upstream_clients
from oa_agent.db.models import Skill
from oa_agent.executor.catalog import SkillState
from oa_agent.executor.executor import Identity, ToolError, ToolExecutor
from oa_agent.executor.tags import EmptyTagProvider
from oa_agent.executor.visibility import PrincipalContext, VisibilityService
from oa_agent.observability import conversation
from oa_agent.observability.events import RunRecorder
from oa_agent.runtime.graphs import travel_query
from oa_agent.runtime.graphs.travel_query import RunCancelled, chat_enabled
from oa_agent.runtime.intervention import DEFAULT_EXPIRE_MINUTES, InterventionService
from oa_agent.runtime.llm import build_chat_model, resolve_model
from oa_agent.runtime.releases import Release, ReleaseError
from oa_agent.runtime.run_service import (
    CANCEL_REQUESTED, CANCELLED, FAILED, RUNNING, SUCCEEDED, TERMINAL, WAITING_CONFIRMATION, WAITING_HUMAN,
    StaleState,
)
from oa_agent.runtime_state import AppRuntime

log = logging.getLogger(__name__)

CHINA_TZ = timezone(timedelta(hours=8))
_tag_provider = EmptyTagProvider()

# 错误""「提示文案」配置组的字"
USER_MESSAGE_KEYS = {
    "OFFICE_TOKEN_EXPIRED": "office_token_expired",
    "OFFICE_API_NOT_CONFIGURED": "office_api_not_configured",
    "UPSTREAM_NOT_CONFIGURED": "upstream_not_configured",
    "INVALID_ARGUMENT": "invalid_argument",
    "TOOL_NOT_AVAILABLE": "tool_not_available",
    "SKILL_DISABLED": "skill_disabled",
    "RUN_CANCELLED": "run_cancelled",
    "HUMAN_TERMINATED": "human_terminated",
    "INTERVENTION_EXPIRED": "intervention_expired",
}


def load_settings(rt: AppRuntime, group: str) -> dict:
    """配置组的生效值（热生效；库不可用时沿用最近一次成功读取的值，保证对话不依赖监控库）"""
    if hasattr(rt, "group_settings"):
        return rt.group_settings(group)
    return GROUPS[group].defaults()


def setting(rt: AppRuntime, group: str, key: str):
    value = load_settings(rt, group).get(key)
    return GROUPS[group].field(key).default if value is None or value == "" else value


def text(rt: AppRuntime, key: str) -> str:
    """「提示文案」配置组里的文案"""
    return str(setting(rt, "messages", key))


def launch_policy(rt: AppRuntime) -> chat_launch.LaunchPolicy:
    c = {k: int(setting(rt, "chat", k)) for k in ("assertion_max_ttl_seconds", "assertion_clock_skew_seconds",
                                                   "launch_code_ttl_seconds", "ticket_ttl_minutes",
                                                   "remint_before_seconds")}
    return chat_launch.LaunchPolicy(max_assertion_ttl=c["assertion_max_ttl_seconds"],
                                    clock_skew=c["assertion_clock_skew_seconds"],
                                    launch_ttl=c["launch_code_ttl_seconds"], ticket_ttl=c["ticket_ttl_minutes"] * 60,
                                    remint_before=c["remint_before_seconds"])


def office_client(rt: AppRuntime) -> OfficeApiClient:
    oa = load_settings(rt, "oa")
    try:
        return OfficeApiClient(oa.get("office_api_base_url"), oa.get("success_codes"))
    except OfficeApiError as exc:
        raise AppError(503, exc.code, exc.message) from exc


def tool_clients(rt: AppRuntime) -> dict[str, OfficeApiClient]:
    try:
        return upstream_clients(load_settings(rt, "oa"))
    except OfficeApiError as exc:
        raise AppError(503, exc.code, exc.message) from exc


def _model(rt: AppRuntime, config: dict):
    if config.get("intent_mode") == "rules":
        return None
    try:
        with rt.session() as db:
            cfg = resolve_model(db, rt.vault, rt.tenant_id, config.get("llm_model_id"))
    except SQLAlchemyError:
        log.exception("读取 LLM 配置失败，走规则解析")
        return None
    return (build_chat_model(cfg), cfg) if cfg else None


# ---- 发布配置 / Skill（P4、P5 "engine 提供；未提供时用代码默认值） ----

def current_release(rt: AppRuntime) -> Release:
    provider = getattr(rt.engine, "release_provider", None)
    if provider is None:
        return Release(None, None, dict(travel_query.DEFAULT_CONFIG))
    return provider.current()


def release_for_run(rt: AppRuntime, run: Run) -> Release:
    """运行绑定的发布快照：恢复时沿用，发布新版本不影响执行中的运行"""
    provider = getattr(rt.engine, "release_provider", None)
    if provider is None or not run.config_release_id:
        return Release(run.config_release_id, None, dict(travel_query.DEFAULT_CONFIG))
    try:
        return provider.get(run.config_release_id)
    except ReleaseError as exc:
        raise AppError(exc.status, exc.code, exc.message) from exc


def _iso_utc(value) -> str | None:
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.isoformat() + "Z" if hasattr(value, "isoformat") else None
    return value.isoformat()


def _skills_with_tools(rt: AppRuntime) -> list[SkillState]:
    engine = rt.engine
    if engine is None or not hasattr(engine, "available_skills"):
        return []
    return [s for s in engine.available_skills() if any(engine.registry.get(t) for t in s.tools)]


def visible_skills_for(rt: AppRuntime, oa: str, *, office_token: str = "") -> list[SkillState]:
    """按可见性规则裁"Skill；库不可用时不阻断，回退为不过滤"""
    skills = _skills_with_tools(rt)
    if not skills:
        return []
    tags = _tag_provider.load_tags(oa, office_token)
    principal = PrincipalContext(oa=oa, tags=tags)
    try:
        with rt.session() as db:
            names = [s.name for s in skills]
            rows = db.scalars(
                sa.select(Skill).where(Skill.tenant_id == rt.tenant_id, Skill.name.in_(names))
            ).all()
            name_to_id = {row.name: row.id for row in rows}
            visible_ids = VisibilityService.filter_skill_ids(
                db, tenant_id=rt.tenant_id, skill_ids=name_to_id.values(), principal=principal
            )
    except SQLAlchemyError:
        log.exception("Skill 可见性查询失败，回退为不过滤：oa=%s", oa)
        return skills
    out: list[SkillState] = []
    for skill in skills:
        sid = name_to_id.get(skill.name)
        if sid is None or sid in visible_ids:
            out.append(skill)
    return out


def skill_menu(rt: AppRuntime, *, oa: str | None = None, office_token: str = "") -> list[dict]:
    """员工欢迎页展示的可用功能：只含已启用、校验通过且至少有一个已注册 Tool "Skill"""
    skills = visible_skills_for(rt, oa, office_token=office_token) if oa else _skills_with_tools(rt)
    return [{
        "name": s.name,
        "display_name": s.display_name,
        "description": s.description,
        "examples": s.examples,
        "created_at": _iso_utc(getattr(s, "created_at", None)),
        "newest_tool_created_at": _iso_utc(getattr(s, "newest_tool_created_at", None)),
    } for s in skills]


def chat_available(rt: AppRuntime) -> bool:
    """欢迎页提示用：当前发布允许聊天且有可用模型"""
    config = current_release(rt).config
    if not chat_enabled(config):
        return False
    try:
        with rt.session() as db:
            return resolve_model(db, rt.vault, rt.tenant_id, config.get("llm_model_id")) is not None
    except Exception:  # noqa: BLE001 —"只影响欢迎页文案
        log.exception("检查聊天可用性失")
        return False


def check_skills(rt: AppRuntime) -> None:
    checker = getattr(rt.engine, "skill_checker", None)
    if checker is not None:
        checker()


# ---- 运行上下文（KV"----

def _ctx_key(run_id: str) -> str:
    return f"run:ctx:{run_id}"


def _reply_key(run_id: str) -> str:
    return f"run:reply:{run_id}"


def remember_run(rt: AppRuntime, run_id: str, *, session_key: str, oa: str, thread_id: str, channel: str,
                 message: str) -> None:
    rt.kv.current.set(_ctx_key(run_id), json.dumps({"session_key": session_key, "oa": oa, "thread_id": thread_id,
                                                    "channel": channel, "message": message}),
                      int(setting(rt, "chat", "run_context_ttl_hours")) * 3600)


def run_context(rt: AppRuntime, run_id: str) -> dict | None:
    raw = rt.kv.current.get(_ctx_key(run_id))
    return json.loads(raw) if raw else None


def store_reply(rt: AppRuntime, run_id: str, reply: dict) -> None:
    conversation.record_reply(rt.session, run_id, reply)
    try:
        rt.kv.current.set(_reply_key(run_id), json.dumps(reply, ensure_ascii=False, default=str),
                          int(setting(rt, "chat", "reply_cache_minutes")) * 60)
    except Exception:  # noqa: BLE001 — 回复缓存失败只影响员工轮询看到结果，不影响运行本身
        log.exception("缓存运行回复失败 run_id=%s", run_id)


def load_reply(rt: AppRuntime, run_id: str) -> dict | None:
    raw = rt.kv.current.get(_reply_key(run_id))
    return json.loads(raw) if raw else None


def employee_session(rt: AppRuntime, run: Run) -> tuple[ChatSession | None, dict | None, str]:
    """重验身份：运行上下文存在、会话仍有效、且会话员工与运行员工一致。返回 (会话, 上下文)；不可用时原因。"""
    ctx = run_context(rt, run.run_id)
    if ctx is None:
        return None, None, (
            f"运行上下文已过期（超过 {setting(rt, 'chat', 'run_context_ttl_hours')} 小时）"
            "或缓存已清空），无法恢复")
    if session is None:
        return None, ctx, "员工会话已过期，无法以员工身份继续执行"
    if session.oa != run.oa or ctx.get("oa") != run.oa:
        return None, ctx, "会话身份与运行不一致，拒绝恢复"
    return session, ctx, ""


# ---- 对话入口 ----

def guard_message(rt: AppRuntime, session: ChatSession, message: str, client_msg_id: str) -> None:
    if not message.strip():
        raise AppError(422, "VALIDATION_ERROR", "消息不能为空")
    max_chars = int(setting(rt, "chat", "message_max_chars"))
    if len(message) > max_chars:
        raise AppError(422, "VALIDATION_ERROR", f"消息不能超过 {max_chars} ")
    try:
        with rt.session() as db:
            if threads.get_owned(db, thread_id=session.thread_id, oa=session.oa) is None:
                raise AppError(404, "THREAD_NOT_FOUND", "会话不存")
    except AppError:
        raise
    except Exception:  # noqa: BLE001 —"库不可用时不挡对话（"touch 降级一致）；库可用则已删必 404
        log.exception("校验会话线程失败（不阻断）：thread=%s", session.thread_id)
    limit = int(setting(rt, "runtime", "chat_rate_limit_per_min"))
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    if rt.kv.current.incr(f"chat:rl:{session.oa}:{minute}", 60) > limit:
        raise AppError(429, "RATE_LIMITED", "发送太频繁，请稍后再试")
    if not rt.kv.current.set_nx(f"chat:msg:{session.oa}:{client_msg_id}", "1",
                                int(setting(rt, "chat", "message_dedupe_seconds"))):
        raise AppError(409, "DUPLICATE_MESSAGE", "该消息已提交，请勿重复发")


def handle_message(rt: AppRuntime, session: ChatSession, message: str, correlation_id: str,
                   session_key: str = "", on_delta: Callable[[str], None] | None = None) -> dict:
    """on_delta：流式回调，每次收到回复正文的新增片段；渠道自行累积并节流刷新"""
    _supersede_waiting(rt, session)
    return start_run(rt, session, message, correlation_id, session_key=session_key, on_delta=on_delta)


def _supersede_waiting(rt: AppRuntime, session: ChatSession) -> None:
    """同一会话线程发新消息时，仍在等待人工的旧运行作废（其 Checkpoint 将被新运行覆盖，无法再恢复）"""
    engine = rt.engine
    try:
        with rt.session() as db:
            waiting = db.scalars(sa.select(Run).where(Run.tenant_id == rt.tenant_id,
                                                      Run.thread_id == session.thread_id,
                                                      Run.run_status == WAITING_HUMAN)).all()
        for run in waiting:
            with rt.session() as db, db.begin():
                engine.runs.transition(run.run_id, WAITING_HUMAN, CANCELLED, db=db, ended_at=utcnow(),
                                       error_code="RUN_SUPERSEDED", error_summary="员工发起了新的请")
                InterventionService.cancel_open_for_run(db, run.run_id, f"employee:{session.oa}", "员工发起了新的请")
            rec = engine.recorder_for_run(run)
            rec.event("run_superseded", status=CANCELLED, operator_id=f"employee:{session.oa}")
            rec.event("run_end", status=CANCELLED, error_code="RUN_SUPERSEDED")
    except (SQLAlchemyError, StaleState):
        log.exception("作废等待中的旧运行失败：thread=%s", session.thread_id)


def start_run(rt: AppRuntime, session: ChatSession, message: str, correlation_id: str, *, session_key: str,
              run_id: str | None = None, parent_run_id: str | None = None, operator: str | None = None,
              on_delta: Callable[[str], None] | None = None) -> dict:
    engine = rt.engine
    release = current_release(rt)
    rec = RunRecorder(run_id=run_id or new_run_id(), thread_id=session.thread_id, oa=session.oa,
                      correlation_id=correlation_id, sink=engine.sink)
    tracked = engine.runs.start(rec, channel=session.channel, agent_id=travel_query.AGENT_ID,
                                workflow_id=travel_query.WORKFLOW_ID, workflow_version=travel_query.WORKFLOW_VERSION,
                                business_type=travel_query.BUSINESS_TYPE, config_release_id=release.release_id,
                                parent_run_id=parent_run_id, message=message)
    conversation.record_user(rt.session, rec, session.channel, message)
    try:
        with rt.session() as db, db.begin():
            threads.touch_on_user_message(
                db,
                thread_id=session.thread_id,
                oa=session.oa,
                channel=session.channel or "",
                user_text=message,
            )
    except AppError:
        raise  # "THREAD_NOT_FOUND（已"非本人）；勿"DB 故障混吞
    except Exception:  # noqa: BLE001 —"线程元数据失败不挡对"
        log.exception("更新线程元数据失败：thread=%s", session.thread_id)
    if operator:
        rec.event("operator_retry", status=RUNNING, operator_id=operator, metadata={"parent_run_id": parent_run_id})
    if session_key:
        try:
            remember_run(rt, rec.run_id, session_key=session_key, oa=session.oa, thread_id=session.thread_id,
                         channel=session.channel, message=message)
        except Exception:  # noqa: BLE001 —"只影响之后能否恢"重试，不影响本次对话
            log.exception("保存运行上下文失败：%s", rec.run_id)
    return _drive(rt, rec, session, release.config, tracked,
                  lambda ctx: engine.invoke(ctx, message, session.thread_id), check=True, on_delta=on_delta)


def _load_long_term_memory(rt: AppRuntime, oa: str) -> str:
    from oa_agent.chat import memory_store as ms

    try:
        with rt.session() as db:
            rows, _ = ms.list_active(db, tenant_id=rt.tenant_id, oa=oa, limit=ms.ACTIVE_MAX, offset=0)
            return ms.format_injection(rows)
    except SQLAlchemyError:
        log.exception("加载员工长期记忆失败：oa=%s", oa)
        return ""


def _build_context(rt: AppRuntime, rec: RunRecorder, session: ChatSession, config: dict,
                   on_delta: Callable[[str], None] | None = None) -> travel_query.RunContext:
    return travel_query.RunContext(
        on_delta=on_delta,
        recorder=rec,
        identity=Identity(oa=session.oa, authorization=session.office_token),
        executor=ToolExecutor(rt.engine.live_registry, tool_clients(rt),
                              int(setting(rt, "oa", "tool_remark_max_chars"))),
        today=datetime.now(CHINA_TZ).date(),
        model=_model(rt, config),
        config=config,
        skills=visible_skills_for(rt, session.oa, office_token=session.office_token),
        long_term_memory=_load_long_term_memory(rt, session.oa),
        tenant_id=rt.tenant_id,
        thread_id=session.thread_id,
        session_factory=rt.session,
    )


def _drive(rt: AppRuntime, rec: RunRecorder, session: ChatSession, config: dict, tracked: bool,
           call: Callable[[travel_query.RunContext], dict], check: bool = False,
           on_delta: Callable[[str], None] | None = None) -> dict:
    engine = rt.engine
    try:
        try:
            ctx = _build_context(rt, rec, session, config, on_delta)
            if check and (ctx.model is None or not chat_enabled(config)):
                check_skills(rt)  # 能聊天时没有可用 Skill 也照常对话，只是不能查询
            state = call(ctx)
        finally:
            conversation.flush_model_calls(rt.session, rec)
    except RunCancelled:
        final = engine.runs.finish(rec, CANCELLED, error_code="RUN_CANCELLED", error_summary="管理员取消了运行")
        return _error_reply(rt, rec, "RUN_CANCELLED", "", tracked, final)
    except (ToolError, AppError) as exc:
        code = getattr(exc, "code", "RUN_FAILED")
        final = engine.runs.finish(rec, FAILED, error_code=code, error_summary=exc.message)
        return _error_reply(rt, rec, code, exc.message, tracked, final, getattr(exc, "user_message", ""))
    except Exception as exc:  # noqa: BLE001
        log.exception("运行 %s 失败", rec.run_id)
        final = engine.runs.finish(rec, FAILED, error_code="RUN_FAILED", error_summary=f"{type(exc).__name__}: {exc}")
        return _error_reply(rt, rec, "RUN_FAILED", "", tracked, final)

    interrupts = state.get("__interrupt__")
    if interrupts:
        return _handoff(rt, rec, interrupts[0].value or {}, tracked)

    reply = state.get("reply") or {"type": "text", "content": "", "data": None}
    spec = engine.registry.get(state.get("tool") or "")
    detail_id = (state.get("params") or {}).get("id") if spec is not None and spec.result_kind == "object" else None
    final = engine.runs.finish(rec, SUCCEEDED, business_record_id=str(detail_id) if detail_id else None)
    if final != SUCCEEDED:
        reply = {"type": "error", "content": text(rt, "run_cancelled") if final == CANCELLED
                 else text(rt, "upstream_unavailable"), "data": None, "error_code": final.upper()}
    store_reply(rt, rec.run_id, reply)
    return _result(rec, final, reply, tracked)


def _handoff(rt: AppRuntime, rec: RunRecorder, value: dict, tracked: bool) -> dict:
    engine = rt.engine
    code = value.get("error_code") or "UPSTREAM_UNAVAILABLE"
    summary = value.get("error_summary") or ""
    expire = int(setting(rt, "runtime", "intervention_expire_minutes") or DEFAULT_EXPIRE_MINUTES)
    try:
        task_id = engine.interventions.handoff(rec, node_name="human_handoff", error_code=code,
                                               error_summary=summary, expire_minutes=expire)
    except SQLAlchemyError:
        log.exception("创建介入任务失败（监控库不可用？），运行 %s 直接失败", rec.run_id)
        task_id = None
    if task_id is None:
        rec.failed_node = "call_tool"
        status = engine.runs.finish(rec, CANCELLED if _status(rt, rec.run_id) == CANCEL_REQUESTED else FAILED,
                                    error_code=code, error_summary=summary)
        return _error_reply(rt, rec, code, summary, tracked, status)
    reply = {"type": "pending", "content": text(rt, "handoff"), "data": None}
    conversation.record_reply(rt.session, rec.run_id, reply)
    return _result(rec, WAITING_HUMAN, reply, tracked)


def _status(rt: AppRuntime, run_id: str) -> str | None:
    try:
        with rt.session() as db:
            return db.scalar(sa.select(Run.run_status).where(Run.run_id == run_id))
    except SQLAlchemyError:
        return None


def _result(rec: RunRecorder, status: str, reply: dict, tracked: bool) -> dict:
    return {"run_id": rec.run_id, "thread_id": rec.thread_id, "run_status": status, "reply": reply,
            "tool_calls": rec.tool_call_count, "observability": "ok" if tracked else "degraded"}


def user_reply_for(rt: AppRuntime, code: str, message: str = "", hint: str = "") -> dict:
    """hint：office-api 返回给员工的提示语（业务校验失败等），有则原样展示，比通用错误更有用"""
    if hint:
        return {"type": "error", "content": f"业务系统提示：{hint}", "data": None, "error_code": code}
    key = USER_MESSAGE_KEYS.get(code) or ("upstream_unavailable" if code.startswith("UPSTREAM") else "generic_failure")
    content = text(rt, key).replace("{message}", message)
    return {"type": "error", "content": content, "data": None, "error_code": code}


def _error_reply(rt: AppRuntime, rec: RunRecorder, code: str, message: str, tracked: bool,
                 status: str = FAILED, hint: str = "") -> dict:
    reply = user_reply_for(rt, code, message, hint)
    store_reply(rt, rec.run_id, reply)
    return _result(rec, status, reply, tracked)


# ---- 管理操作（权限、CSRF、幂等、审计由 API 层负责；这里只做状态与执行"----

def resume_run(rt: AppRuntime, run: Run, session: ChatSession, operator: str, correlation_id: str,
               decision: dict) -> dict:
    """waiting_human "running，从 Checkpoint 中断点继续（human_handoff 节点收到决定后回"call_tool）"""
    engine = rt.engine
    engine.runs.transition(run.run_id, WAITING_HUMAN, RUNNING, error_code=None, error_summary=None,
                           failed_node=None)
    rec = engine.recorder_for_run(run, correlation_id)
    rec.event("operator_resume", status=RUNNING, operator_id=operator, metadata=decision)
    release = release_for_run(rt, run)
    return _drive(rt, rec, session, release.config, True,
                  lambda ctx: engine.resume(ctx, run.thread_id, decision))


def terminate_run(rt: AppRuntime, run: Run, operator: str, reason: str, db) -> None:
    """waiting_human "failed(HUMAN_TERMINATED)，在调用方事务内执行（与审计同提交）"""
    rt.engine.runs.transition(run.run_id, WAITING_HUMAN, FAILED, db=db, ended_at=utcnow(),
                              error_code="HUMAN_TERMINATED", error_summary=f"管理员终止：{reason}")


def after_terminate(rt: AppRuntime, run: Run, operator: str, reason: str) -> None:
    rec = rt.engine.recorder_for_run(run)
    rec.event("operator_terminate", status=FAILED, operator_id=operator, metadata={"reason": reason})
    rec.event("run_end", status=FAILED, error_code="HUMAN_TERMINATED", error_summary=f"管理员终止：{reason}")
    store_reply(rt, run.run_id, user_reply_for(rt, "HUMAN_TERMINATED"))


def cancel_run(rt: AppRuntime, run: Run, db) -> str:
    """在调用方事务内改状态，返回目标状态；终态或已在取消中抛 409"""
    runs = rt.engine.runs
    now = utcnow()
    if run.run_status == RUNNING:
        runs.transition(run.run_id, RUNNING, CANCEL_REQUESTED, db=db)
        return CANCEL_REQUESTED
    if run.run_status == WAITING_HUMAN:
        runs.transition(run.run_id, WAITING_HUMAN, CANCELLED, db=db, ended_at=now, error_code="RUN_CANCELLED",
                        error_summary="管理员取消了运行")
        return CANCELLED
    if run.run_status == WAITING_CONFIRMATION:
        runs.transition(run.run_id, WAITING_CONFIRMATION, CANCEL_REQUESTED, db=db)
        runs.transition(run.run_id, CANCEL_REQUESTED, CANCELLED, db=db, ended_at=now, error_code="RUN_CANCELLED",
                        error_summary="管理员取消了运行")
        return CANCELLED
    if run.run_status in TERMINAL:
        raise AppError(409, "RUN_ALREADY_ENDED", f"运行已结束（{run.run_status}），无法取消")
    raise AppError(409, "RUN_CANCEL_PENDING", "运行已在取消")


def after_cancel(rt: AppRuntime, run: Run, status: str, operator: str, reason: str) -> None:
    engine = rt.engine
    if status == CANCEL_REQUESTED:
        engine.request_cancel(run.run_id)
    rec = engine.recorder_for_run(run)
    rec.event("operator_cancel", status=status, operator_id=operator, metadata={"reason": reason})
    if status == CANCELLED:
        rec.event("run_end", status=CANCELLED, error_code="RUN_CANCELLED", error_summary="管理员取消了运行")
        store_reply(rt, run.run_id, user_reply_for(rt, "RUN_CANCELLED"))


def retry_run(rt: AppRuntime, run: Run, session: ChatSession, ctx: dict, operator: str, correlation_id: str,
              new_run_id_: str) -> dict:
    """以原员工会话重新执行原消息，新运行记 parent_run_id。结果不推送到员工页面（员工侧需重新提问）"""
    return start_run(rt, session, ctx["message"], correlation_id, session_key=ctx["session_key"],
                     run_id=new_run_id_, parent_run_id=run.run_id, operator=operator)

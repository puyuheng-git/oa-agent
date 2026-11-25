# 模型可见工具结果（脱敏明细）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同轮 observation 与跨轮 history 向模型注入脱敏后的工具结果 JSON，使多轮追问能引用业务字段，同时身份证/银行卡/手机号/工资等不对模型可见。

**Architecture:** 新增 `oa_agent.runtime.model_payload` 统一构建脱敏 JSON；`summarize_tool_data` 与 `_history_summary` 改为调用它；`_history_messages` 对助手消息用更大字数上限；提示词改为「可引用结果、禁止编造」；员工 `respond` 与对话存档路径不改。

**Tech Stack:** Python 3 / pytest / 现有 `redact` / `wrap_untrusted` / LangGraph `oa_assistant`。

**Spec:** [`docs/superpowers/specs/2026-11-24-model-visible-tool-data-design.md`](../specs/2026-11-24-model-visible-tool-data-design.md)

## Global Constraints

- 仅模型侧脱敏；员工表格与 `ConversationMessage` 存档策略不变（仍只 `redact_secrets`）。
- 列表列：优先 `list_columns`，否则 `result.fields`；默认最多 20 行；历史明细默认 6000 字。
- 全局黑名单字段名：身份证/银行卡/口令/手机/工资相关；值形态对齐现有 `_PII_RULES`。
- 本期不做 Tool 字段 `model_hidden` UI；memory 压缩不写业务明细。
- `merge_release_config` 缺省新键用 `DEFAULT_CONFIG`（无需强制重发版）。
- 回复与文档中文；代码标识符英文。
- **Commit 仅在用户明确要求时执行**；计划中的 commit 步骤默认跳过。
- 测试命令在 `backend` 目录：`uv run pytest … -v`。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/oa_agent/runtime/model_payload.py` | **新建**：字段/值脱敏 + 构建 table/record/text 的模型 JSON 字符串 |
| `backend/oa_agent/observability/redact.py` | 可选：导出 `_PII_RULES` 或提供 `redact_pii_value` 供 payload 复用（避免复制正则） |
| `backend/oa_agent/runtime/react/observation.py` | `summarize_tool_data` 改为产出明细 JSON（可接收 columns/max_rows/max_chars） |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | `_history_summary` / `_history_messages` / `DEFAULT_CONFIG` / `AGENT_PROMPT`（及 CHAIN 相关句） |
| `backend/oa_agent/runtime/releases.py` | 新配置项 + 更新 history / max_tool_steps 的 help 文案 |
| `backend/tests/test_model_payload.py` | **新建**：脱敏、截断、列选择、text 围栏 |
| `backend/tests/test_react_runtime_p1.py` | 更新 observation 断言（现为「不要全量 list」） |
| `backend/tests/test_builtin_chat.py` | 更新 text 历史回灌断言（现为「不回灌」） |
| `backend/tests/test_model_visible_history.py` | **新建**：`_history_summary` table/record + `merge_release_config` 缺省回填 |

---

### Task 1: `model_payload` 模块（TDD）

**Files:**
- Create: `backend/oa_agent/runtime/model_payload.py`
- Create: `backend/tests/test_model_payload.py`
- Modify (minimal): `backend/oa_agent/observability/redact.py` — 增加可复用的值级 PII 函数（若直接 import 私有 `_PII_RULES` 不便，则新增公开 API）

**Interfaces:**
- Produces:
  - `is_sensitive_field_name(name: str) -> bool`
  - `scrub_value(field: str, value: Any) -> Any` — 敏感字段名 → `"[已脱敏]"`；否则对 str 跑 PII 值规则
  - `scrub_row(row: dict, columns: list[str]) -> dict`
  - `build_model_payload(*, tool: str, kind: str, data: dict, columns: list[str] | None = None, max_rows: int = 20, max_chars: int = 6000) -> str`
    - `kind` 接受 `list` / `table` / `record` / `text`
    - 返回 **JSON 字符串**（`ensure_ascii=False`）；超 `max_chars` 时截断字符串并在末尾加 `…[截断]`（截断前尽量保证 note 已说明 shown/total）
- Consumes: `oa_agent.observability.redact` 的 PII 规则；`wrap_untrusted`（仅 text）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_model_payload.py
import json
from oa_agent.runtime.model_payload import build_model_payload, is_sensitive_field_name, scrub_value


def test_sensitive_field_names():
    assert is_sensitive_field_name("id_card")
    assert is_sensitive_field_name("员工身份证")
    assert is_sensitive_field_name("bank_card_no")
    assert is_sensitive_field_name("mobile")
    assert is_sensitive_field_name("salary")
    assert is_sensitive_field_name("工资")
    assert not is_sensitive_field_name("amount")
    assert not is_sensitive_field_name("reason")
    assert not is_sensitive_field_name("department")


def test_scrub_value_field_and_pattern():
    assert scrub_value("id_card", "110101199001011234") == "[已脱敏]"
    assert scrub_value("amount", 1200) == 1200
    assert "[身份证]" in str(scrub_value("note", "证件 110101199001011234 完毕")) or "[已脱敏]" in str(
        scrub_value("note", "证件 110101199001011234 完毕")
    )


def test_list_payload_prefers_columns_and_caps_rows():
    rows = [{"id": i, "amount": i * 10, "id_card": "110101199001011234", "reason": f"r{i}"} for i in range(1, 30)]
    text = build_model_payload(
        tool="t.list",
        kind="list",
        data={"list": rows, "total": 29},
        columns=["id", "amount", "id_card", "reason"],
        max_rows=20,
        max_chars=6000,
    )
    payload = json.loads(text)
    assert payload["kind"] in ("list", "table")
    assert payload["total"] == 29
    assert payload["shown"] == 20
    assert len(payload["items"]) == 20
    assert payload["items"][0]["amount"] == 10
    assert payload["items"][0]["id_card"] == "[已脱敏]"
    assert "id_card" not in payload["items"][0] or payload["items"][0]["id_card"] == "[已脱敏]"
    assert set(payload["columns"]) == {"id", "amount", "id_card", "reason"}


def test_record_payload_all_columns():
    text = build_model_payload(
        tool="t.one",
        kind="record",
        data={"item": {"id": "9", "amount": 50, "mobile": "13800138000"}},
        columns=["id", "amount", "mobile"],
        max_rows=20,
        max_chars=6000,
    )
    payload = json.loads(text)
    assert payload["kind"] == "record"
    assert payload["item"]["amount"] == 50
    assert payload["item"]["mobile"] == "[已脱敏]"


def test_text_payload_redacts_and_fences():
    from oa_agent.security.prompt_guard import wrap_untrusted, FENCE_OPEN

    raw = wrap_untrusted("电话 13912345678 可联系", source="builtin", name="sys.time")
    text = build_model_payload(
        tool="builtin.time",
        kind="text",
        data={"text": raw},
        max_chars=6000,
    )
    assert FENCE_OPEN in text or "UNTRUSTED_DATA" in text
    assert "13912345678" not in text
    assert "builtin.time" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_model_payload.py -v`  
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `model_payload.py`（及 redact 小导出）**

实现要点：

```python
# 字段名：lower 后子串匹配
# id_card|idcard|id_no|身份证|证件号
# bank_card|bankcard|bank_account|银行卡|卡号；或同时含 (银行|卡) 与 账号
# password|passwd|pwd|secret|token
# mobile|phone|手机
# salary|wage|工资|薪资

# list/table: items = data.get("list") or data.get("items") or []
# record: item = data.get("item") if dict else {k: data[k] for k in columns}
# text: unwrap_untrusted → redact PII on body → wrap_untrusted(..., source="tool_result", name=tool, max_chars=...)
# JSON 顶层含 tool/kind/total/shown/columns/items 或 item 或 text；note 说明截断与「已展示给员工」
```

`redact.py` 建议新增：

```python
def redact_pii(text: str | None, limit: int | None = None) -> str:
    """仅个人信息值形态（不含密钥规则以外的业务保留场景）；供模型 payload 使用。"""
    return _apply(text, _PII_RULES, limit)
```

字段名命中时统一用字面量 `"[已脱敏]"`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_model_payload.py -v`  
Expected: PASS

- [ ] **Step 5: Commit（仅当用户要求）**

```bash
git add backend/oa_agent/runtime/model_payload.py backend/oa_agent/observability/redact.py backend/tests/test_model_payload.py
git commit -m "feat: add model_payload builder with PII scrub for tool results"
```

---

### Task 2: 接入 observation（`summarize_tool_data`）

**Files:**
- Modify: `backend/oa_agent/runtime/react/observation.py` — `summarize_tool_data`
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py` — `call_tool` 成功分支调用处（约 2649 行），传入 columns / max_rows / max_chars
- Modify: `backend/tests/test_react_runtime_p1.py` — `test_observation_prompt_has_summary_not_full_list`

**Interfaces:**
- Consumes: `build_model_payload`
- Produces: `summarize_tool_data(tool, data, *, kind=None, columns=None, max_rows=20, max_chars=6000) -> str`

- [ ] **Step 1: 改失败测试**

将 `test_observation_prompt_has_summary_not_full_list` 改为：

```python
def test_observation_prompt_includes_redacted_rows():
    summary = summarize_tool_data(
        "office.list",
        {"list": [{"id": 1, "amount": 100, "id_card": "110101199001011234"}, {"id": 2, "amount": 200}], "total": 2},
        kind="list",
        columns=["id", "amount", "id_card"],
        max_rows=20,
    )
    assert '"amount": 100' in summary or '"amount":100' in summary.replace(" ", "")
    assert "110101199001011234" not in summary
    assert "[已脱敏]" in summary
    obs = build_observation(
        task_id="t", run_id="r", execution_id="e", tool="office.list",
        round_no=1, step_index=0, status="success", summary=summary,
    )
    text = format_observations_for_prompt([obs])
    assert "Tool observations" in text
    assert "office.list" in text
```

- [ ] **Step 2: 跑测试确认旧实现失败**

Run: `uv run pytest tests/test_react_runtime_p1.py::test_observation_prompt_includes_redacted_rows -v`  
Expected: FAIL（旧 summary 无 amount JSON）

- [ ] **Step 3: 实现 `summarize_tool_data` 委托 + call_tool 传参**

```python
# observation.py
def summarize_tool_data(tool, data, *, kind=None, columns=None, max_rows=20, max_chars=6000):
    from oa_agent.runtime.model_payload import build_model_payload
    return build_model_payload(
        tool=tool, kind=kind or "object", data=data or {},
        columns=list(columns) if columns else None,
        max_rows=max_rows, max_chars=max_chars,
    )
```

在 `call_tool` 成功处（现 `summary = summarize_tool_data(name, data, kind=kind)`）改为：

```python
cols = list(spec.columns()) if spec else None  # ToolSpec.columns() = list_columns or result_fields[:6]
# 规格要求：优先 list_columns 否则全部 result_fields（详情用全 fields）
if spec:
    if kind == "list":
        cols = list(spec.list_columns or spec.result_fields)
    elif kind == "record":
        cols = list(spec.result_fields)
    else:
        cols = None
max_rows = ctx.num("model_result_max_rows")  # Task 3 加入 DEFAULT 前先用 DEFAULT_CONFIG.get 或字面 20 兜底
max_chars = ctx.num("model_history_detail_chars") if "model_history_detail_chars" in ctx.config or True else 6000
summary = summarize_tool_data(
    name, data, kind=kind, columns=cols,
    max_rows=ctx.num("model_result_max_rows") if hasattr(ctx, "num") else 20,
    max_chars=min(int(ctx.config.get("max_observation_tokens") or 24000),
                  int(ctx.config.get("model_history_detail_chars") or 6000)),
)
```

注意：`RunContext.num` 在键缺失时回退 `DEFAULT_CONFIG[key]`——因此 Task 3 必须先把键写入 `DEFAULT_CONFIG`，或本任务与 Task 3 合并顺序：**先加 DEFAULT_CONFIG 键再改 call_tool**。

**推荐顺序调整：** 若本任务单独做，call_tool 内对缺失键用：

```python
max_rows = int(ctx.config.get("model_result_max_rows") or 20)
max_chars = int(ctx.config.get("model_history_detail_chars") or 6000)
```

避免 `num()` KeyError。

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_react_runtime_p1.py::test_observation_prompt_includes_redacted_rows tests/test_model_payload.py -v`  
Expected: PASS

- [ ] **Step 5: Commit（仅当用户要求）**

```bash
git add backend/oa_agent/runtime/react/observation.py backend/oa_agent/runtime/graphs/oa_assistant.py backend/tests/test_react_runtime_p1.py
git commit -m "feat: inject redacted tool rows into ReAct observations"
```

---

### Task 3: 配置项 + `_history_summary` / `_history_messages`

**Files:**
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py` — `DEFAULT_CONFIG`、`_history_summary`、`_history_messages`
- Modify: `backend/oa_agent/runtime/releases.py` — 配置字段与 help
- Create: `backend/tests/test_model_visible_history.py`
- Modify: `backend/tests/test_builtin_chat.py` — text 回灌断言

**Interfaces:**
- Consumes: `build_model_payload`；`ctx.tools()` 取当前 ToolSpec 的 columns
- Produces: history 助手消息为脱敏 JSON；`model_result_max_rows` / `model_history_detail_chars` 进入发布配置

- [ ] **Step 1: 写/改失败测试**

```python
# backend/tests/test_model_visible_history.py
import json
from types import SimpleNamespace
from oa_agent.runtime.graphs import oa_assistant
from oa_agent.runtime.releases import merge_release_config


def test_merge_fills_model_payload_defaults():
    merged = merge_release_config({"history_turns": 4})  # 旧快照缺新键
    assert merged["model_result_max_rows"] == 20
    assert merged["model_history_detail_chars"] == 6000


def test_history_summary_table_includes_amounts_not_id_card():
    spec = SimpleNamespace(
        name="query_my_travel_expense_list",
        result_kind="list",
        result_fields=("id", "amount", "id_card", "reason"),
        list_columns=("id", "amount", "reason"),
        columns=lambda: ("id", "amount", "reason"),
    )
    ctx = SimpleNamespace(
        config=dict(oa_assistant.DEFAULT_CONFIG),
        tools=lambda: {spec.name: (spec, None)},
        num=lambda key: oa_assistant.DEFAULT_CONFIG[key],
    )
    state = {
        "intent": oa_assistant.TOOL,
        "tool": spec.name,
        "params": {"month": "2026-10"},
        "steps": [],
    }
    reply = {
        "content": "table markdown",
        "data": {
            "kind": "table",
            "tool": spec.name,
            "total": 2,
            "items": [
                {"id": "1", "amount": 900, "id_card": "110101199001011234", "reason": "出差A"},
                {"id": "2", "amount": 100, "id_card": "110101199001011235", "reason": "出差B"},
            ],
        },
    }
    summary = oa_assistant._history_summary(state, reply, ctx)
    assert "900" in summary
    assert "出差A" in summary
    assert "110101199001011234" not in summary


def test_history_messages_assistant_uses_detail_chars():
    cfg = {**oa_assistant.DEFAULT_CONFIG, "history_message_chars": 50, "model_history_detail_chars": 200}
    ctx = SimpleNamespace(config=cfg, num=lambda key: cfg[key])
    long_json = "x" * 180
    history = [{"role": "user", "content": "hi" * 40}, {"role": "assistant", "content": long_json}]
    msgs = oa_assistant._history_messages(history, ctx)
    human = [m for m in msgs if m[0] == "human"][0][1]
    ai = [m for m in msgs if m[0] == "ai"][0][1]
    assert len(human) <= 50
    assert len(ai) == 180  # 未超过 200
```

改 `test_builtin_chat.py` 中 `test_builtin_time_result_surfaces_in_reply_without_feeding_model_history`：

- 重命名为 `test_builtin_time_result_surfaces_in_reply_and_feeds_redacted_history`
- 断言：`summary` **包含**时区或时间相关正文（或围栏内脱敏正文），且 **仍含** `builtin.time`；`UNTRUSTED_DATA` 可出现在 summary（给模型）；员工 `reply["content"]` 仍无围栏标记。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_model_visible_history.py tests/test_builtin_chat.py::test_builtin_time_result_surfaces_in_reply_and_feeds_redacted_history -v`  
Expected: FAIL

- [ ] **Step 3: 改 DEFAULT_CONFIG + releases + history 函数**

`DEFAULT_CONFIG` 增加：

```python
"model_result_max_rows": 20,
"model_history_detail_chars": 6000,
```

`releases.py` 在 MEMORY 组 `history_message_chars` 附近增加两项；更新：

- `history_turns` help：改为「查询结果历史含脱敏业务明细（敏感字段除外）」
- `history_message_chars` help：注明「主要限制员工原话；助手查询明细见 model_history_detail_chars」
- `max_tool_steps` help：去掉「模型看不到任何返回数据」，改为「引用由服务端取值；模型可见脱敏摘要」

`_history_summary` 核心逻辑：

```python
def _history_summary(state, reply, ctx):
    data = reply.get("data") or {}
    kind = data.get("kind")
    tool_name = data.get("tool") or state.get("tool")
    spec = (ctx.tools().get(tool_name) or (None, None))[0] if tool_name else None
    max_rows = ctx.num("model_result_max_rows")
    max_chars = ctx.num("model_history_detail_chars")
    if state.get("intent") == TOOL and kind in ("table", "list", "record", "text"):
        if kind in ("table", "list"):
            cols = list((spec.list_columns or spec.result_fields) if spec else [])
            # reply table 用 items；无 columns 时从 items[0] keys 推断
        elif kind == "record":
            cols = list(spec.result_fields) if spec else list((data.get("item") or {}).keys())
        else:
            cols = None
        payload_kind = "list" if kind == "table" else kind
        body = build_model_payload(
            tool=tool_name or "",
            kind=payload_kind,
            data=data,
            columns=cols or None,
            max_rows=max_rows,
            max_chars=max_chars,
        )
        # 可选：前缀查询条件一行，便于「那上个月的」
        params = {k: v for k, v in (state.get("params") or {}).items() if k not in ("page", "limit")}
        if params and kind != "text":
            return f"条件 {json.dumps(params, ensure_ascii=False)}\n{body}"
        return body
    # 非工具：原 chat 逻辑 peel_think_wrap
    ...
```

`_history_messages`：

```python
user_chars = ctx.num("history_message_chars")
assistant_chars = ctx.num("model_history_detail_chars")
...
content = content[: user_chars if role == "human" else assistant_chars]
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_model_visible_history.py tests/test_builtin_chat.py tests/test_model_payload.py tests/test_workflows.py -v`  
Expected: PASS（`test_workflows` 若断言 content == 完整 DEFAULT_CONFIG，新键会自动进入）

- [ ] **Step 5: Commit（仅当用户要求）**

```bash
git add backend/oa_agent/runtime/graphs/oa_assistant.py backend/oa_agent/runtime/releases.py backend/tests/test_model_visible_history.py backend/tests/test_builtin_chat.py
git commit -m "feat: put redacted tool details into chat history for the model"
```

---

### Task 4: 提示词与文案

**Files:**
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py` — `AGENT_PROMPT`、`CHAIN_PROMPT` 中相关句
- Test: 轻量断言提示词常量含新约束（可放在 `test_model_visible_history.py`）

**Interfaces:**
- Produces: 模型可见「可引用 observations/历史 JSON；禁止编造未出现字段；系统表为准；脱敏占位不可猜」

- [ ] **Step 1: 写断言测试**

```python
def test_agent_prompt_allows_citing_tool_results():
    assert "看不到" not in oa_assistant.AGENT_PROMPT or "可根据" in oa_assistant.AGENT_PROMPT
    assert "禁止编造" in oa_assistant.AGENT_PROMPT or "不要编造" in oa_assistant.AGENT_PROMPT
    assert "observations" in oa_assistant.AGENT_PROMPT.lower() or "工具结果" in oa_assistant.AGENT_PROMPT or "查询 JSON" in oa_assistant.AGENT_PROMPT
```

（实现时以实际中文文案为准，断言与最终句子对齐。）

- [ ] **Step 2: 跑测试确认当前文案失败**

Run: `uv run pytest tests/test_model_visible_history.py::test_agent_prompt_allows_citing_tool_results -v`  
Expected: FAIL（仍含「你看不到…业务数据」且无新句）

- [ ] **Step 3: 替换提示词段落**

将回答要求中：

```
- 你看不到员工的任何 OA 业务数据：不要编造…
```

改为（可微调，保持 JSON-only 约束）：

```
- 可根据 Tool observations 与历史中的查询结果 JSON 回答追问、对比与总结；禁止编造其中未出现的字段值或办理结果
- 列表/详情的规范展示以系统表格或卡片为准；chat 用文字补充，不要用 HTML 假表替代系统表
- 结果中的「[已脱敏]」等占位不得猜测还原
- 你只能通过工具查询，不能替员工提交、修改或审批任何业务；…
```

`CHAIN_PROMPT` 中「勿编造字段值」保留；可补一句「observations 中的 JSON 可供引用」。

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_model_visible_history.py::test_agent_prompt_allows_citing_tool_results -v`  
Expected: PASS

- [ ] **Step 5: Commit（仅当用户要求）**

```bash
git add backend/oa_agent/runtime/graphs/oa_assistant.py backend/tests/test_model_visible_history.py
git commit -m "docs: allow model to cite redacted tool JSON in prompts"
```

---

### Task 5: 回归与验收剧本（单元级）

**Files:**
- Modify/Create: `backend/tests/test_model_visible_history.py`（补 record + 行数截断 + 敏感不出现在 summary）
- 不强制真连 LLM；用 payload/history 断言覆盖规格 §10 的可自动化部分

- [ ] **Step 1: 补充验收向测试**

```python
def test_list_history_caps_at_20_rows():
    items = [{"id": str(i), "amount": i} for i in range(25)]
    ...
    summary = oa_assistant._history_summary(...)
    payload = json.loads(summary.split("\n", 1)[-1] if summary.startswith("条件") else summary)
    assert payload["shown"] == 20
    assert len(payload["items"]) == 20
    assert payload["total"] == 25


def test_record_history_followup_fields_present():
    # item 含 amount/reason，summary JSON 可被追问引用
    ...
```

- [ ] **Step 2: 跑全量相关套件**

Run:

```bash
uv run pytest tests/test_model_payload.py tests/test_model_visible_history.py tests/test_react_runtime_p1.py tests/test_builtin_chat.py tests/test_workflows.py tests/test_prompt_guard.py -v
```

Expected: PASS

- [ ] **Step 3: 手工验收清单（记录在 PR/回复中，不写代码）**

1. 查列表 → 追问「金额最高的是哪笔」→ 回答命中列表中的金额/事由。  
2. 查详情 → 追问展示字段 → 答对。  
3. 首轮员工端仍是系统表。  
4. 构造含手机号字段的 Tool 结果 → 模型侧 JSON 为 `[已脱敏]`，员工表仍可见原值（若接口返回了）。

- [ ] **Step 4: Commit（仅当用户要求）**

```bash
git add backend/tests/test_model_visible_history.py
git commit -m "test: cover model-visible tool data acceptance cases"
```

---

## Spec coverage checklist

| 规格条款 | 任务 |
|----------|------|
| 同轮 observation 注入明细 | Task 2 |
| 跨轮 history 注入明细 | Task 3 |
| 全局黑名单 + 值形态 | Task 1 |
| 仅模型侧脱敏 | Task 1–3（不改 respond/conversation） |
| 20 行 / 6000 字 / list_columns | Task 1–3 |
| 紧凑 JSON | Task 1 |
| text 回灌 + 围栏 | Task 1、3 |
| 配置缺省回填 | Task 3 |
| 提示词可引用、禁编造 | Task 4 |
| memory 不写明细 | 无改 remember（显式不改）；Task 3 不往 memory 塞明细 |
| 验收剧本 | Task 5 |
| 不做 model_hidden UI | 全计划未包含 |

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-11-24-model-visible-tool-data.md`.

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每任务新开子代理，任务间复查  
2. **Inline Execution** — 本会话按 `executing-plans` 批量推进并设检查点  

选哪一种？

"""配置中心的配置组定义（设计 §5.2）。数据库连接组单独存 bootstrap.json，不在此处。

每个字段的 help 是给管理员看的详细说明（作用、影响、建议值）；int 字段的 min/max 是硬边界，
安全相关字段的边界即安全底线，后台无法设置得更宽松。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: str  # str | int | url | list | secret | upstreams | text | bool | enum
    default: object = None
    help: str = ""
    min: int | None = None
    max: int | None = None      # int：取值上限；text/str：字数上限
    options: tuple[tuple[str, str], ...] = ()   # enum：(值, 名称)
    unit: str = ""

    def public(self) -> dict:
        out = {"key": self.key, "label": self.label, "kind": self.kind, "help": self.help, "default": self.default}
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.options:
            out["options"] = [{"value": v, "label": label} for v, label in self.options]
        if self.unit:
            out["unit"] = self.unit
        return out


@dataclass(frozen=True)
class GroupDef:
    name: str
    label: str
    apply_mode: str  # 生效方式说明
    fields: tuple[FieldDef, ...] = field(default_factory=tuple)
    testable: bool = False
    description: str = ""

    def field(self, key: str) -> FieldDef | None:
        return next((f for f in self.fields if f.key == key), None)

    def defaults(self) -> dict:
        return {f.key: f.default for f in self.fields if f.kind != "secret"}


def _text(key: str, label: str, default: str, help_: str, max_len: int = 500) -> FieldDef:
    return FieldDef(key, label, "text", default, help_ + "（留空恢复默认文案）", max=max_len)


GROUPS: dict[str, GroupDef] = {
    g.name: g
    for g in (
        GroupDef(
            "redis",
            "Redis",
            "测试通过后热切换",
            (
                FieldDef("url", "地址", "url",
                         help="如 redis://10.0.0.5:6379，不要把密码写在地址里（填在下面的密码栏）。"
                              "留空使用进程内存（单实例可用，重启后后台登录与员工会话失效）。"),
                FieldDef("db", "DB 序号", "int", 0, "Redis 库序号，与其他系统共用 Redis 时用不同序号隔离。",
                         min=0, max=255),
                FieldDef("password", "密码", "secret", help="只写不读：保存后只显示末 4 位；留空表示不修改。"),
            ),
            testable=True,
            description="存放后台会话、员工对话会话、限流计数和防重复标记。保存前会先测试连接，"
                        "切换时把内存中的会话迁移过去，已登录的管理员和员工不受影响。",
        ),
        GroupDef(
            "oa",
            "业务上游 / 连接器（兼容原 OA 对接）",
            "热生效",
            (
                FieldDef("mint_base_url", "员工 token 签发地址", "url",
                         help="OA 宿主页 / 企微入口换员工 Authorization 的 HTTP 基址（调用 /agent/token/mint）。"
                              "与业务上游分离；未配置时兼容读取旧「office-api 主地址」。"),
                FieldDef("upstreams", "业务上游地址", "upstreams", [],
                         "认同同一员工 Authorization 的业务 HTTP 面（名称自定，勿写死域名）。"
                         "每项标识 + 名称 + 基址；Tool 只引用标识与相对路径。"
                         "入口建权后可带 token 调用目录内上游上已声明的接口；各接口仍须 OA 侧业务授权。"),
                FieldDef("default_upstream_key", "新建 Tool 默认上游", "str", "office",
                         help="仅影响新建 Tool 的默认上游标识，无协议特权；须存在于上方列表中（有列表时）。"),
                FieldDef("gateway_secret", "AGENT_GATEWAY_SECRET（mint 用）", "secret",
                         help="向签发入口换员工 token 时使用的网关密钥，须与 OA 侧配置一致。只写不读。"),
                FieldDef("assertion_hmac_secret", "OA assertion HMAC 密钥", "secret",
                         help="校验 OA 宿主页签发的员工身份断言（assertion）的密钥，须与 OA 侧配置一致。只写不读。"),
                FieldDef("allowed_frame_origins", "允许嵌入的 OA 域名", "list", [], "如 https://oa.example.com"),
                FieldDef("success_codes", "业务上游成功码", "list", ["0", "200"], "响应 code 字段视为成功的取值"),
                FieldDef("business_hint_max_chars", "业务提示语最大长度", "int", 200,
                         "业务上游返回的 msg/message 提示语（如「该单据不存在」）展示给员工前的截断长度。"
                         "过长的提示语多为接口异常堆栈，截断可避免泄露内部信息。", min=50, max=1000, unit="字"),
                FieldDef("tool_remark_max_chars", "备注字段最大长度", "int", 100,
                         "Tool 返回结果中 remark（备注）字段的截断长度，超出部分以「…」结尾。"
                         "备注通常是员工自由填写的长文本，截断可以让表格保持可读。", min=20, max=2000, unit="字"),
            ),
            description="业务连接器（兼容原「OA 对接」配置组 key=oa）：与业务系统只走 HTTP。"
                        "入口（宿主页 assertion / 企微 / IdP）完成身份与 token 签发；"
                        "业务数据只来自已配置上游以该员工 Authorization 返回的结果，且仅限已声明的 Tool/写契约。"
                        "旧字段 office_api_base_url / extra_upstreams 读取时自动映射，保存请用新字段。",
        ),
        GroupDef(
            "chat",
            "员工对话",
            "热生效（会话类时长只影响之后新建/续期的会话）",
            (
                FieldDef("message_max_chars", "单条消息最大长度", "int", 500,
                         "员工一次能发送的最大字数。超过时提示「消息不能超过 N 字」。"
                         "调大会让模型输入变长、费用增加；上限 2000 与接口限制一致。", min=20, max=2000, unit="字"),
                FieldDef("message_dedupe_seconds", "重复消息拦截时长", "int", 300,
                         "同一条消息（相同客户端消息 ID）在这段时间内重复提交会被拒绝，防止网络重试导致重复执行。",
                         min=10, max=3600, unit="秒"),
                FieldDef("launch_code_ttl_seconds", "启动码有效期", "int", 60,
                         "OA 宿主页拿到启动码后必须在这段时间内打开助手页，过期需重新进入。"
                         "启动码会出现在地址栏，越短越安全。", min=10, max=300, unit="秒"),
                FieldDef("ticket_ttl_minutes", "对话会话有效期", "int", 30,
                         "员工打开助手页后的会话时长（页面会在到期前自动续期）。"
                         "实际有效期不超过 OA 签发的员工 token 有效期。", min=5, max=480, unit="分钟"),
                FieldDef("remint_before_seconds", "员工 token 提前续签时间", "int", 300,
                         "员工 token 剩余有效期少于该值时，续期会话时向 OA 重新签发，避免查询中途过期。",
                         min=60, max=1800, unit="秒"),
                FieldDef("assertion_max_ttl_seconds", "OA assertion 最长有效期", "int", 60,
                         "OA 宿主页签发的身份断言（assertion）exp 最多比当前时间晚多少秒，超过视为无效。"
                         "越短越不容易被截获重放。", min=10, max=300, unit="秒"),
                FieldDef("assertion_clock_skew_seconds", "OA 与助手的时钟容差", "int", 30,
                         "校验 assertion 过期时间时允许的两台服务器时钟偏差。服务器已做时间同步时保持默认即可。",
                         min=0, max=120, unit="秒"),
                FieldDef("run_context_ttl_hours", "运行上下文保留时长", "int", 24,
                         "转人工、重试需要的运行上下文（只存会话引用）保留多久；超过后管理员无法再恢复或重试该运行。",
                         min=1, max=168, unit="小时"),
                FieldDef("reply_cache_minutes", "转人工结果缓存时长", "int", 60,
                         "转人工的运行处理完成后，结果在缓存中保留多久供员工页面轮询取回。",
                         min=5, max=1440, unit="分钟"),
                FieldDef("result_poll_seconds", "转人工结果轮询间隔", "int", 5,
                         "员工页面在等待人工处理结果时，多久查询一次结果。越短越及时，但请求更多。",
                         min=2, max=60, unit="秒"),
            ),
            description="员工从 OA 打开助手页、发送消息的相关限制与时长。助手的回答方式（角色、多轮对话、压缩、串联、"
                        "流式）在「工作流配置」中按版本发布。",
        ),
        GroupDef(
            "messages",
            "提示文案",
            "热生效",
            (
                _text("office_token_expired", "登录过期", "登录已过期，请重新打开 OA 助手页。",
                      "员工 token 失效（OA 端登出或过期）时给员工的提示"),
                _text("office_api_not_configured", "助手未配置", "助手尚未完成配置，请联系管理员。",
                      "未配置 office-api 地址时给员工的提示"),
                _text("upstream_not_configured", "查询地址未配置", "该查询功能尚未完成配置，请联系管理员。",
                      "Tool 指向的 office-api 地址不存在时给员工的提示"),
                _text("invalid_argument", "查询条件有误", "查询条件有误：{message}",
                      "Tool 参数校验失败时给员工的提示，{message} 会替换为具体原因"),
                _text("tool_not_available", "功能未开放（Tool）", "该功能未对你开放。",
                      "Tool 已停用、未注册或对当前员工不可见时给员工的提示"),
                _text("skill_disabled", "功能未开放（Skill）", "该功能暂未开放，请联系管理员。",
                      "没有可用 Skill 且不能聊天时给员工的提示"),
                _text("run_cancelled", "请求被取消", "该请求已被取消。", "管理员取消运行后给员工的提示"),
                _text("human_terminated", "人工终止", "业务系统暂时不可用，该请求已由管理员终止，请稍后重新提问。",
                      "管理员在介入中心终止运行后给员工的提示"),
                _text("intervention_expired", "介入过期", "业务系统暂时不可用，请稍后重新提问。",
                      "人工介入任务超时未处理时给员工的提示"),
                _text("upstream_unavailable", "业务系统不可用", "业务系统暂时不可用，请稍后再试。",
                      "office-api 超时、5xx 等故障时给员工的提示（不展示接口原文）"),
                _text("handoff", "已转人工", "业务系统暂时不可用，已转人工处理。处理完成后结果会显示在这里，你也可以稍后重新提问。",
                      "上游故障且发布配置为「转人工介入」时给员工的提示"),
                _text("generic_failure", "通用失败", "处理失败，请稍后再试。", "其他未分类错误时给员工的提示"),
                _text("no_skill", "没有可用功能", "暂时没有可用的查询功能，请联系管理员。",
                      "帮助回复、企业微信欢迎语中没有任何可用 Skill 时的说明"),
                _text("wecom_group", "企业微信群聊", "为保护个人数据，请在单聊中向我提问。",
                      "员工在企业微信群里 @ 机器人时的回复"),
                _text("wecom_unsupported", "企业微信不支持的消息", "目前只支持文字（或语音转文字）消息，请直接输入你要查询的内容。",
                      "员工在企业微信发送图片、文件等消息时的回复"),
                _text("wecom_identity_failed", "企业微信身份解析失败", "暂时无法确认你的 OA 身份，请稍后再试；如持续出现请联系管理员。",
                      "按企业微信账号解析 OA 身份失败时的回复"),
                _text("wecom_working", "企业微信处理中", "正在查询…",
                      "企业微信收到消息后、结果出来前先显示的文字"),
                _text("wecom_pending_suffix", "企业微信转人工补充说明",
                      "企业微信里不会自动推送处理结果，请稍后重新提问获取结果。",
                      "转人工时附在企业微信回复末尾的说明"),
                _text("wecom_truncated_suffix", "企业微信内容截断说明", "…（内容过长已截断，请缩小查询范围）",
                      "回复超过企业微信单条上限（约 20KB）被截断时附在末尾的说明"),
                _text("wecom_welcome", "企业微信欢迎语开头", "你好，我是 OA 助手，可以帮你查询本人的：",
                      "员工进入机器人单聊时欢迎语的开头，后面自动列出可用功能"),
            ),
            description="员工能看到的固定提示。只能改文字，不能改变触发条件。",
        ),
        GroupDef(
            "wecom",
            "企业微信",
            "热生效（约 10 秒内自动连接/重连；BotID 或 Secret 留空即断开；处理线程数重启生效）",
            (
                FieldDef("bot_id", "BotID", "str", help="企业微信管理后台 → 智能机器人 → API 模式选「长连接」后获取"),
                FieldDef("secret", "Secret", "secret", help="长连接专用 Secret（不是回调模式的 Token/EncodingAESKey）"),
                FieldDef("ws_url", "长连接地址", "str", "wss://openws.work.weixin.qq.com", "一般不用改"),
                FieldDef("ping_interval_seconds", "心跳间隔", "int", 30,
                         "多久向企业微信发一次应用层心跳。超过「2 × 心跳间隔 + 15 秒」收不到任何下行数据即判定断线并重连。"
                         "企业微信建议 30 秒。", min=10, max=120, unit="秒"),
                FieldDef("backoff_max_seconds", "断线重连最长等待", "int", 60,
                         "断线后按 1、2、4…秒指数退避重连，单次等待不超过该值。", min=5, max=600, unit="秒"),
                FieldDef("kicked_backoff_seconds", "被替换后重试等待", "int", 300,
                         "同一机器人在别处建立了新连接（本连接被踢）后，等待多久再尝试连接。"
                         "多实例部署会互相踢下线，请保证只部署一个实例。", min=60, max=3600, unit="秒"),
                FieldDef("message_dedupe_seconds", "重复推送拦截时长", "int", 600,
                         "企业微信可能重复推送同一条消息，按消息 ID 在这段时间内去重。", min=60, max=86400, unit="秒"),
                FieldDef("stream_flush_ms", "流式刷新间隔", "int", 800,
                         "开启流式输出时，模型逐字生成的内容每隔多久推送一次到企业微信。"
                         "过短会触发企业微信频率限制，建议 500～1500 毫秒。", min=200, max=5000, unit="毫秒"),
                FieldDef("workers", "并发处理线程数", "int", 4,
                         "同时处理的企业微信消息数，超出的消息排队。修改后需重启服务。", min=1, max=16, unit="个"),
            ),
            description="企业微信智能机器人以长连接方式接入：员工在单聊中提问，身份按企业微信账号向 OA 解析。"
                        "单条消息约 20KB 的上限是企业微信平台限制，不可配置。",
        ),
        GroupDef(
            "security",
            "后台安全",
            "热生效（会话时长只影响之后登录/续期的会话；密码长度只影响之后设置的密码）",
            (
                FieldDef("login_max_failures", "连续登录失败锁定次数", "int", 5,
                         "同一账号连续输错密码达到该次数后锁定。安全底线：不超过 10 次。", min=3, max=10, unit="次"),
                FieldDef("login_lock_minutes", "账号锁定时长", "int", 15,
                         "账号被锁定后多久自动解锁。安全底线：不少于 5 分钟。", min=5, max=1440, unit="分钟"),
                FieldDef("ip_max_failures", "单 IP 登录失败上限", "int", 30,
                         "同一来源 IP 在统计窗口内登录失败达到该次数后，该 IP 暂时不能登录（防撞库）。",
                         min=10, max=200, unit="次"),
                FieldDef("ip_window_minutes", "单 IP 失败统计窗口", "int", 15,
                         "统计单 IP 登录失败次数的时间窗口，也是被拦截后的等待时长。", min=5, max=1440, unit="分钟"),
                FieldDef("session_absolute_hours", "后台会话最长时长", "int", 8,
                         "管理员登录后最多保持多久，到期必须重新登录（无论是否在操作）。安全底线：不超过 24 小时。",
                         min=1, max=24, unit="小时"),
                FieldDef("session_idle_minutes", "后台会话空闲超时", "int", 30,
                         "管理员多久没有操作就自动退出。安全底线：不超过 4 小时。", min=5, max=240, unit="分钟"),
                FieldDef("password_min_length", "密码最小长度", "int", 12,
                         "管理员密码的最少位数（另需包含大写、小写、数字、符号中至少 3 类）。"
                         "安全底线：不少于 12 位。只对之后设置的密码生效。", min=12, max=64, unit="位"),
                FieldDef("idempotency_seconds", "重复提交拦截时长", "int", 3,
                         "后台写操作带同一个 Idempotency-Key 在这段时间内重复提交会被拒绝，防止双击重复执行。",
                         min=1, max=60, unit="秒"),
            ),
            description="管理员登录与操作的安全策略。每项都有不可突破的安全底线（取值范围即底线），"
                        "密码哈希算法、CSRF 校验、审计等不可关闭。",
        ),
        GroupDef(
            "runtime",
            "运行参数",
            "热生效",
            (
                FieldDef("event_retention_days", "事件保留天数", "int", 180,
                         "运行事件（时间线）保留多久，过期自动清理。对话记录与审计不受影响。", min=7, max=3650, unit="天"),
                FieldDef("run_timeout_seconds", "单次运行超时（秒）", "int", 60,
                         "一次对话运行超过该时长仍未结束，巡检会标记为超时（timed_out）。", min=10, max=600, unit="秒"),
                FieldDef("stuck_threshold_seconds", "疑似卡住阈值（秒）", "int", 30,
                         "运行中超过该时长但未超时，在监控中标记「疑似卡住」，不改变状态", min=5, max=600, unit="秒"),
                FieldDef("chat_rate_limit_per_min", "每员工每分钟消息上限", "int", 30,
                         "单个员工每分钟最多发送的消息数，超出提示「发送太频繁」，防止刷接口和模型费用失控。",
                         min=1, max=10000, unit="条"),
                FieldDef("intervention_expire_minutes", "人工介入任务有效期（分钟）", "int", 30,
                         "超时未处理的介入任务过期，对应运行标记为 failed(INTERVENTION_EXPIRED)",
                         min=5, max=1440, unit="分钟"),
                FieldDef("watchdog_interval_seconds", "巡检间隔", "int", 30,
                         "后台巡检（超时标记、介入过期、事件清理）多久执行一次。", min=5, max=300, unit="秒"),
                FieldDef("purge_interval_minutes", "过期事件清理间隔", "int", 60,
                         "多久清理一次超过保留天数的运行事件。", min=10, max=1440, unit="分钟"),
                FieldDef("stats_cache_seconds", "监控统计缓存时长", "int", 30,
                         "监控总览的统计结果缓存多久。设为 0 表示每次实时统计（数据量大时会变慢）。",
                         min=0, max=600, unit="秒"),
                FieldDef("p95_min_samples", "P95 最少样本数", "int", 20,
                         "运行耗时样本少于该数量时，P95 显示「样本不足」，避免少量数据得出误导性结论。",
                         min=5, max=1000, unit="个"),
                FieldDef("export_max_messages", "对话导出单次上限", "int", 50000,
                         "导出对话记录（JSONL）时单次最多导出的消息条数，超出需缩小时间范围。",
                         min=1000, max=500000, unit="条"),
                FieldDef("export_max_days", "对话导出最大时间跨度", "int", 92,
                         "导出对话记录时开始与结束时间的最大间隔，防止一次导出过多数据拖慢数据库。",
                         min=1, max=366, unit="天"),
                FieldDef("write_workflows_enabled", "启用固定写 Workflow", "bool", False,
                         "开启后允许运行行程报销等固定写闭环（查→草稿→员工确认→提交）。"
                         "office-api 写接口未就绪或探针失败时应保持关闭；默认关闭。"),
                FieldDef("http_allow_hosts", "内置 HTTP 全局白名单", "list", [],
                         "内置工具 sys.http 的默认允许主机（如 api.example.com 或 *.example.com）；"
                         "单个 Tool 的沙箱策略里配置了 http_allow_hosts 时以 Tool 为准。"
                         "留空且 Tool 也未配置时，sys.http 一律拒绝（SANDBOX_REQUIRED）。高风险工具默认关闭。"),
                FieldDef("tool_routing_mode", "工具路由模式（全局默认）", "enum", "legacy_prompt",
                         "决定助手「听到员工一句话后，怎么从众多查询能力里挑出该调哪个接口」。"
                         "这里是全局默认：新对话若所属工作流发布里没单独写路由模式，就用本项；"
                         "若流程配置已发布并写了路由模式，以那次发布为准（跑着的旧对话也不变）。"
                         "行程报销等「固定写流程」不走这里，仍按白名单写 Workflow。"
                         "各模式白话说明——"
                         "提示词海选：把可见查询能力的说明书塞给模型一次选；Tool 不多时最简单，默认兼容。"
                         "先选 Skill 再选 Tool：先判断属于哪类业务（如行程报销），再只在该类里选接口，减少跨业务误选。"
                         "检索召回再精选：先按关键词从能力库里捞一批候选，再让模型精选填参；Tool 变多时更合适。"
                         "元工具渐进披露：首轮不塞业务说明书；模型（或服务端）先 search_capabilities 再 get_tool_schema，"
                         "受「元工具往返上限」约束后再填参，避免一次塞入全部 Tool。"
                         "确定性优先：能靠固定说法/规则（含「先列表再详情」串联）直接定下就不问模型；定不下再走下面的回退模式。"
                         "小路由大填参：先便宜地定「用哪一个 Tool」，再用主模型只带这一份参数说明去填参，省 Token。",
                         options=(
                             ("legacy_prompt", "提示词海选（兼容）"),
                             ("skill_then_tool", "先选 Skill 再选 Tool"),
                             ("retrieve_then_tool", "检索召回再精选"),
                             ("meta_search", "元工具渐进披露"),
                             ("deterministic_first", "确定性优先"),
                             ("router_then_fill", "小路由大填参"),
                         )),
                FieldDef("prompt_topk", "提示词候选 Tool 上限", "int", 8,
                         "在「提示词海选」或「检索后再精选」时，最多把多少个查询能力的说明书放进模型提示词。"
                         "员工当前可见的 Tool 总数不超过该值时，相当于全部放进去，不会截断。"
                         "Tool 很多时调小可省 Token、减轻选错；调太小可能漏掉真正相关的能力。默认 8。",
                         min=1, max=64, unit="个"),
                FieldDef("routing_skill_method", "Skill 选择方式", "enum", "rules_then_llm",
                         "只在「先选 Skill 再选 Tool」「小路由大填参」里生效：系统如何判断员工问的是哪一类业务。"
                         "规则优先，失败再用模型：先用关键词/内置规则猜；猜不准再交给模型（推荐，稳且省）。"
                         "仅规则：完全不调模型选类，只认固定说法，省费用但覆盖面窄。"
                         "仅模型：主要靠模型分类；本期若未单独配置路由模型，实际仍按相关度打分，不保证独立小模型。",
                         options=(
                             ("rules_then_llm", "规则优先，失败再用模型"),
                             ("rules", "仅规则"),
                             ("llm", "仅模型"),
                         )),
                FieldDef("retrieve_topk", "检索召回条数", "int", 8,
                         "「检索召回再精选」与「元工具渐进披露」的 search_capabilities 共用："
                         "先从全部可见 Tool 里捞出最相关的前 N 个。"
                         "N 越大越不易漏检，但后续说明书更长、费用更高；N 太小可能捞不到正确能力。默认 8。",
                         min=1, max=64, unit="个"),
                FieldDef("retrieve_backend", "检索后端", "enum", "keyword",
                         "「检索召回再精选」用什么方式找候选。"
                         "关键词：按员工原话与 Tool 名称/说明的用词匹配（本期默认，无需额外服务）。"
                         "向量：语义相似度召回；向量服务尚未接通时系统会强制改用关键词，并在调用过程事件里标明降级，不会静默假装向量已通。",
                         options=(("keyword", "关键词"), ("embedding", "向量（未就绪则降级）"))),
                FieldDef("retrieve_must_include_recent", "必留最近用过 Tool 数", "int", 2,
                         "检索召回时，强制把本会话线程里「最近成功用过」的若干个 Tool 留在候选里"
                         "（方便员工接着问「那上个月的呢」「再看详情」）。"
                         "设为 0 表示不强行保留，完全按相关度捞。默认 2。",
                         min=0, max=16, unit="个"),
                FieldDef("meta_max_rounds", "元工具往返上限", "int", 3,
                         "仅「元工具渐进披露」：search_capabilities / get_tool_schema 最多往返几次，防止无限追问说明书。"
                         "用尽仍未选中业务 Tool 时会向员工澄清（若开启低置信澄清）。默认 3。",
                         min=1, max=10, unit="次"),
                FieldDef("deterministic_fallback_mode", "确定性未命中回退模式", "enum", "skill_then_tool",
                         "仅在「确定性优先」下使用：当固定规则认不出员工意图时，改走哪一种选 Tool 方式。"
                         "不能再选「确定性优先」本身，否则会自己套自己。"
                         "建议保持「先选 Skill 再选 Tool」或「提示词海选」；Tool 很多时可用「检索召回再精选」。",
                         options=(
                             ("legacy_prompt", "提示词海选"),
                             ("skill_then_tool", "先选 Skill 再选 Tool"),
                             ("retrieve_then_tool", "检索召回再精选"),
                             ("router_then_fill", "小路由大填参"),
                         )),
                FieldDef("router_model_id", "路由用模型 ID", "str", None,
                         "「小路由大填参」等模式在 stage=router 选 Tool 时使用的模型。"
                         "请填「LLM 配置」里模型的数字 ID（主键），不要填密钥或接口地址。"
                         "留空则与工作流默认对话模型相同；填参（stage=fill）始终用默认对话模型。"
                         "适合把分类交给更便宜的小模型，主模型只负责填参。",
                         max=64),
                FieldDef("routing_clarify_on_low_confidence", "低置信时向员工澄清", "bool", True,
                         "系统拿不准该用哪个查询能力时怎么处理。"
                         "开启（推荐）：直接问员工「你想查哪一类？」等，不瞎猜接口，避免查错单据。"
                         "关闭：按各模式自己的兜底继续往下选（可能选错或落到帮助回复）。"
                         "主要影响「先选 Skill」「小路由大填参」等在候选不清时的行为。"),
                FieldDef("routing_trace_enabled", "写入路由过程事件", "bool", True,
                         "是否把「怎么选出这个 Tool」的过程记进运行事件，供「调用过程」页查看与统计。"
                         "开启（推荐）：写入开始路由、各阶段候选、最终决定、向员工澄清等事件；"
                         "事件里只留能力名称、分数、耗时，不含员工全文密钥或业务明细。"
                         "关闭：仍会记真实的 Tool 调用起止，但统计页上的模式占比、澄清率等会变少或显示能力降级说明。"
                         "排障、验收路由策略时请保持开启。"),
            ),
            description="运行监控、超时判定、人工介入、数据保留与导出，以及「如何从员工原话落到查询接口」的工具路由参数。"
                        "路由只影响候选可见范围，真正查数仍走员工 token 与业务上游授权；不代替权限判定。",
        ),
        GroupDef(
            "import",
            "Apipost 导入",
            "热生效",
            (
                FieldDef("timeout_seconds", "拉取超时", "int", 10,
                         "从 Apipost 分享链接拉取接口文档的超时时间。", min=3, max=60, unit="秒"),
                FieldDef("max_kb", "文档大小上限", "int", 2000,
                         "单次拉取的接口文档最大体积，超出拒绝导入。", min=100, max=10000, unit="KB"),
                FieldDef("max_targets", "单次最多接口数", "int", 20,
                         "一个分享链接里最多导入多少个接口。", min=1, max=100, unit="个"),
                FieldDef("list_columns", "列表默认列数", "int", 6,
                         "生成 Tool 草稿时，列表结果默认显示前几个有显示名称的字段（之后可在 Tool 表单里调整）。",
                         min=1, max=20, unit="列"),
            ),
            description="在「Tool 管理」中从 Apipost 分享链接生成 Tool 草稿时的限制。"
                        "出于安全考虑只允许访问 docs.apipost.net，地址不可配置。",
        ),
        GroupDef(
            "mcp",
            "MCP 连接",
            "热生效（只影响之后新建/修改的 MCP 连接）",
            (
                FieldDef("allowed_origins", "远程 MCP 地址白名单", "list", [],
                         "sse / http 类型的 MCP 连接地址必须命中此名单（协议+域名，可带端口，"
                         "如 https://mcp.example.com）。未配置时拒绝所有远程地址，请先在这里配置。"),
            ),
            description="出站 MCP 连接的全局安全边界。MCP 连接本身在「MCP 连接」页配置，密钥只写不读。",
        ),
        GroupDef(
            "packs",
            "领域包",
            "热生效",
            (
                FieldDef(
                    "disabled_ids",
                    "已禁用领域包",
                    "list",
                    [],
                    "写入包 id 后该包对员工侧不可见（规则/Skill/Workflow 聚合会排除）。"
                    "未列入的包仍按各自默认启用状态生效；默认空列表表示不额外禁用。",
                ),
                FieldDef(
                    "enabled_ids",
                    "已显式启用领域包",
                    "list",
                    [],
                    "写入默认关闭的包 id 后可显式启用；若同一 id 也在 disabled_ids，禁用优先。"
                    "默认启用的包无需列入。",
                ),
            ),
            description="Domain Pack 启停覆盖。默认启用的包（如 oa_travel）无需列出；"
                        "要关闭的包写入 disabled_ids，默认关闭但需开启的包写入 enabled_ids。",
        ),
        GroupDef(
            "idp",
            "身份提供者",
            "热生效",
            (
                FieldDef(
                    "demo_idp_enabled",
                    "启用 Demo IdP",
                    "bool",
                    False,
                    "开启后允许用共享口令建立本地 demo 会话（无 OA/office）。"
                    "仅供本地开发与自动化测试；生产环境务必保持关闭。",
                ),
                FieldDef(
                    "demo_shared_secret",
                    "Demo 共享口令",
                    "str",
                    "",
                    "Demo IdP 校验用的本地共享口令（明文存配置，仅限本机）。"
                    "与入站 payload.secret 一致才签发主体；生产勿开启 Demo。",
                    max=256,
                ),
                FieldDef(
                    "channel_idp_map_json",
                    "渠道到 IdP 映射",
                    "text",
                    '{"oa_web":"oa_assertion","wecom":"wecom","demo":"demo"}',
                    "JSON 对象，键为渠道 ID、值为 IdP ID；非法 JSON 或非对象会回落默认映射，"
                    "缺少的默认渠道也会逐项回落。"
                    "预留：运行时入口尚未统一走 verify_channel；改映射暂不影响现网 OA/企微 launch。",
                    max=4000,
                ),
            ),
            description="身份提供者（IdP）与本地 Demo 入口。"
                        "生产环境通常使用 OA 宿主页 assertion 或企微；本地开发可启用 Demo IdP（无 office 上游）。"
                        "Demo 默认关闭；开启后仍须正确共享口令才能建会话。"
                        "channel_idp_map_json 当前为预留配置，待运行时入口统一接入 verify_channel 后生效。",
        ),
    )
}


def secret_name(group: str, key: str) -> str:
    return f"setting.{group}.{key}"


def default(group: str, key: str):
    f = GROUPS[group].field(key)
    return f.default if f else None

# 交付备注：Agent 运行时契约（A 期）

**日期：** 2026-11-20  
**规格：** [`docs/superpowers/specs/2026-11-20-agent-runtime-contract-design.md`](../superpowers/specs/2026-11-20-agent-runtime-contract-design.md)  
**状态：** 已交付

## 范围

本期只交付运行时契约（A）：选路改为「确定性窄门 → Skill 两级 → 低置信澄清」。全局默认 `tool_routing_mode=deterministic_first`，回退 `skill_then_tool`，低置信澄清保持开启。候选只来自对该员工可见且启用的目录 Skill 绑定（未绑 Skill 的 `builtin` 例外）；孤儿非 builtin、未确认开放的 MCP、Skill Pack 不进选路。配置真相页、单项人工迁移、可解释轨迹与回归集一并交付。录入智能化（B）未做。

## 迁移步骤

配置优先级不变：工作流发布快照优先于全局 runtime 默认。不自动改已发布快照，不改进行中 Run / Checkpoint。

1. **改全局默认。** 无路由键的对话回落 `deterministic_first`。已写出 `legacy_prompt` 的快照仍按海选生效。
2. **看真相页。** 管理端路由观测「配置真相」核对 `global_mode` / `global_fallback`、在用工作流快照是否与全局一致，以及 `legacy_prompt_releases` 待迁移清单。无数据时显示暂无。
3. **人工迁 draft。** 对清单中的单项点「迁移到契约默认」：二次确认并看 diff 后，把 `deterministic_first` + `skill_then_tool` + clarify=true 写入该工作流草稿。审计 `routing.snapshot.migrate`。接口返回 `next_step: publish`。也可「标记确认保留海选」，只记审计、降低清单噪音，不改快照。
4. **发布。** 管理员自行发布草稿后，新会话才按契约选路。禁止一键改全部已发布。

## 风险

现网主工作流若发布快照仍钉 `legacy_prompt`，只改全局默认时员工体感不变。以会话绑定的 release 快照为准；须按真相页清单逐项迁 draft 再发布。历史孤儿按契约不可选，用清单改绑或保持禁用，不恢复海选兼容后门。

## A/B 边界

| A（本期） | B（后置，须服从本契约） |
|-----------|-------------------------|
| 默认模式、候选闸门、真相页、迁移清单、MCP Server Skill、轨迹、回归 | Tool/业务接入向导少填、模型分析 schema/文案 |
| 入库须绑 Skill、种类校验（最小） | Skill 优质说明生成、向导交互大改 |
| Pack 排除选路 | Pack 挂目录 Skill 的说明层产品化 |

B 不得再制造孤儿，也不得绕过种类约束。

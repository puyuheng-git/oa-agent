# 交付：Agent Export 向导（替代 catalog 导入）

| 项 | 内容 |
|---|---|
| 日期 | 2026-11-16 |
| Spec | `docs/superpowers/specs/2026-11-16-agent-export-wizard-design.md` |
| Plan | `docs/superpowers/plans/2026-11-16-agent-export-wizard.md` |

## 已落地

- Service：`logic/ExportInspectorImpl` + `logic/AgentExportInvokeImpl`；`Export.php` 仅门面转发；删除 `AgentExportRegistry`
- open-oa：`POST /agent/export/{discover,describe,probe}`；`invoke` = Bearer + 网关密钥；下线 `export-catalog`
- Agent：向导 API `/v1/admin/tools/export-wizard/*`；Tools 页「接入 Export 向导」；运行时 invoke 带网关密钥与 `call`/`op`

## 行程 Tool 重建（操作）

1. 后台 → Tool 管理 → **接入 Export 向导**
2. service：`out_attendance/go_out_application`
3. 方法：`getTravelExpensePageList`（call=`page_list`）/ `getTravelExpenseOneByParams`（call=`one_by_params`）
4. 填写测试员工 oa 与参数 → 测试接口 → 测通后入库 → **启用**
5. 返回字段可参考旧 Registry：`id,date,client_name,total_amount,status,status_text,...`

## 验收（环境依赖）

- [ ] 向导 discover/describe/probe 通
- [ ] 缺网关密钥 invoke 失败
- [ ] 业务页直接 ANew 不受影响
- [ ] 行程对话查询与同账号一致

未在本机对真实 open-oa/Service 联调前，标为「外部依赖未验证」。

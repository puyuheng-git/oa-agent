### Task 3: AuthUser「Authorization 优先」+ detail 强制 oa

**Files:**
- Modify: `D:\MYOA\webroot\puyueheng\site\office-api\app\middleware\AuthUser.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\office-api\app\controller\out_attendance\GoOutTravelExpense.php`（`detail` 方法）

**Interfaces:**
- Produces: 请求带 `Authorization` 时一律 `checkLogin`；无头时保持原 `user_id` 行为
- Produces: `detail` 内 `$queryParams['oa'] = $this->request->oa`

**Steps:**

- [ ] **Step 1: 改 AuthUser 分支**

在已通过 `noneedverifylogin` 检查之后：

```php
$authorization = $request->header('Authorization');
if (!empty($authorization)) {
    $userInfo = $userService->checkLogin($authorization, true, $userFields);
} elseif (in_array($path, $loginWhiteUrls)) {
    // 保留旧：白名单强制 token（若仍需要）
    ...
} else {
    // 原 user_id 逻辑
}
```

补齐 hr_dept_id 逻辑与现网一致；空用户抛 `USER_NOT_LOGIN`。

- [ ] **Step 2: detail 强制 oa**

与 `index`/`list` 相同：`$queryParams['oa'] = $this->request->oa;`

- [ ] **Step 3: 验证**

1. 旧客户端仅 `user_id` 仍可访问 list（回归）  
2. 仅 Authorization（mint 出的 token）可访问 index/detail，且 detail 他人 id 返回空/失败  

---

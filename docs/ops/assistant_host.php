<?php
/**
 * OA 智能助手宿主页：校验 OA 登录 → 服务端签发身份断言 → 向 Agent 换一次性启动码 → 进入对话页
 * 整页：/general/ds/agent/assistant_host.php（输出 iframe）
 * 悬浮挂件：/general/ds/agent/assistant_host.php?mode=embed（302 跳转到对话页）
 * 环境变量：AGENT_URL（Agent 根地址）、OA_ASSERTION_HMAC_SECRET（与 Agent 后台「OA 对接」配置一致）
 * 断言与员工 office token 都不进浏览器，浏览器只拿到 60 秒一次性的 launch_code
 *
 * 部署：复制到 OA 的 general/ds/agent/assistant_host.php（按环境改 AGENT_URL / 密钥 / CHAT_UI_URL）
 * @filesource assistant_host.php
 */

include_once 'inc/session.php';

/**
 * 输出失败提示并结束请求；错误详情只写服务端日志，不展示给用户
 * @param string $msg 给员工看的提示（GBK）
 * @param string $logMsg 写入 error_log 的排查信息，为空则不记录
 * @return void 直接 exit
 */
function assistantHostFail($msg, $logMsg)
{
    if ($logMsg != '')
    {
        error_log('[assistant_host] ' . $logMsg);
    }
    echo '<!DOCTYPE html><html><head><meta charset="GBK"><title>OA 智能助手</title></head>'
        . '<body style="margin:0;padding:3em 1em;font:14px/1.6 sans-serif;color:#666;text-align:center">'
        . $msg . '</body></html>';
    exit;
}

/**
 * 构造并签名身份断言：base64url(UTF-8 JSON) + "." + hex(HMAC-SHA256)
 * @param string $oa OA 账号（LOGIN_USER_ID）
 * @param int $uid OA 用户 UID
 * @param string $userName 显示名（GBK）
 * @param string $secret 与 Agent 共享的 HMAC 密钥
 * @return string 断言字符串
 */
function assistantHostAssertion($oa, $uid, $userName, $secret)
{
    // PHP 5.2 的 json_encode 只接受 UTF-8，GBK 字段必须先转码
    $payload = array(
        'oa'           => iconv('GBK', 'UTF-8//IGNORE', $oa),
        'uid'          => (int)$uid,
        'display_name' => iconv('GBK', 'UTF-8//IGNORE', $userName),
        'exp'          => time() + 50,
        'nonce'        => md5(uniqid(mt_rand(), true)),
        'iss'          => 'oa-host',
        'aud'          => 'oa-langgraph',
    );
    $body = rtrim(strtr(base64_encode(json_encode($payload)), '+/', '-_'), '=');
    return $body . '.' . hash_hmac('sha256', $body, $secret);
}

/**
 * 服务端调用 Agent /v1/chat/launch，用断言换一次性启动码
 * @param string $agentUrl Agent 根地址（不带末尾 /）
 * @param string $assertion 已签名的断言
 * @return array array(launch_code, 失败原因)；成功时失败原因为空串
 */
function assistantHostLaunch($agentUrl, $assertion)
{
    $ch = curl_init($agentUrl . '/v1/chat/launch');
    curl_setopt_array($ch, array(
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode(array('assertion' => $assertion)),
        CURLOPT_HTTPHEADER     => array('Content-Type: application/json'),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_TIMEOUT        => 5,
    ));
    $resp = curl_exec($ch);
    $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curlErr = curl_error($ch);
    curl_close($ch);

    if ($resp === false)
    {
        return array('', 'curl: ' . $curlErr);
    }
    $data = json_decode($resp, true);
    // launch_code 为 URL 安全字符，校验格式后才拼进地址
    if ($status == 200 && isset($data['launch_code']) && preg_match('/^[A-Za-z0-9_-]{10,128}$/', $data['launch_code']))
    {
        return array($data['launch_code'], '');
    }
    $code = isset($data['error']['code']) ? $data['error']['code'] : 'UNEXPECTED_RESPONSE';
    $detail = isset($data['error']['message']) ? $data['error']['message'] : substr($resp, 0, 200);
    return array('', 'HTTP ' . $status . ' ' . $code . ' ' . iconv('UTF-8', 'GBK//IGNORE', $detail));
}

session_start();
session_write_close();

header('Content-Type: text/html; charset=GBK');
// 响应里含一次性启动码，禁止缓存
header('Cache-Control: no-store');

// 登录校验：未登录不签断言，只返回提示
if (empty($_SESSION['LOGIN_USER_ID']) || empty($_SESSION['LOGIN_UID']))
{
    assistantHostFail('登录已失效，请刷新 OA 页面后重新打开助手', '');
}
$oa = $_SESSION['LOGIN_USER_ID'];
$uid = $_SESSION['LOGIN_UID'];
$userName = empty($_SESSION['LOGIN_USER_NAME']) ? $oa : $_SESSION['LOGIN_USER_NAME'];

// 读取对接配置（生产请用环境变量，勿硬编码）
$agentUrl = rtrim((string)getenv('AGENT_URL'), '/');
$secret = (string)getenv('OA_ASSERTION_HMAC_SECRET');
if ($agentUrl == '' || $secret == '')
{
    assistantHostFail('助手暂不可用，请联系管理员', 'AGENT_URL 或 OA_ASSERTION_HMAC_SECRET 未配置');
}

// 同一员工并发「重新进入」时串行换码，避免 mint/launch 竞态刷出失败页
$lockPath = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'oa_agent_launch_' . md5($oa) . '.lock';
$lockFp = @fopen($lockPath, 'c');
$gotLock = false;
if ($lockFp)
{
    $gotLock = @flock($lockFp, LOCK_EX | LOCK_NB);
    if (!$gotLock)
    {
        // 短等一次：连点时让后到的请求排队，而不是立刻失败
        $gotLock = @flock($lockFp, LOCK_EX);
    }
}
if ($lockFp && !$gotLock)
{
    fclose($lockFp);
    assistantHostFail('正在重新进入，请稍候…', 'launch lock busy oa=' . $oa);
}

try
{
    $result = assistantHostLaunch($agentUrl, assistantHostAssertion($oa, $uid, $userName, $secret));
}
catch (Exception $e)
{
    $result = array('', 'exception: ' . $e->getMessage());
}

if ($lockFp)
{
    @flock($lockFp, LOCK_UN);
    fclose($lockFp);
}

if ($result[0] == '')
{
    assistantHostFail('助手暂不可用，请稍后重试或联系管理员', 'launch 失败 oa=' . $oa . ' ' . $result[1]);
}

$chatUiUrl = rtrim((string)getenv('CHAT_UI_URL'), '/');
if ($chatUiUrl == '') { $chatUiUrl = 'http://127.0.0.1:5173'; }
$chatUrl = $chatUiUrl . '/?launch=' . $result[0];

if (isset($_GET['mode']) && $_GET['mode'] == 'embed')
{
    header('Location: ' . $chatUrl . '&embed=1');
    exit;
}
?>
<!DOCTYPE html>
<html>
<head>
<meta charset="GBK">
<title>OA 智能助手</title>
<style>html,body{margin:0;height:100%;overflow:hidden}iframe{display:block;width:100%;height:100%;border:0}</style>
</head>
<body>
<iframe src="<?php echo htmlspecialchars($chatUrl); ?>"></iframe>
</body>
</html>

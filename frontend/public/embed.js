/*
 * OA 智能助手悬浮挂件。OA 页面引入方式见 docs/ops/user-guide.md §4。
 *
 *   <script>window.oaAgentConfig = { hostUrl: '/general/ds/agent/assistant_host.php?mode=embed' }</script>
 *   <script src="https://agent.example.com/embed.js" charset="utf-8" defer></script>
 *
 * 脚本不携带任何身份或密钥：窗口首次打开时 iframe 请求 OA 服务端 hostUrl，由 OA 校验登录、签发断言、
 * 换取一次性 launch_code 后 302 到 Agent 对话页。保持 ES5 语法以兼容老旧 OA 浏览器。
 */
(function () {
  if (window.__oaAgentEmbedLoaded) return
  window.__oaAgentEmbedLoaded = true

  var cfg = window.oaAgentConfig || {}
  if (!cfg.hostUrl) {
    if (window.console) console.warn('[oa-agent] 未配置 window.oaAgentConfig.hostUrl，挂件未加载')
    return
  }
  var title = cfg.title || 'OA 智能助手'
  var color = cfg.primaryColor || '#1C64F2'
  var width = cfg.width || '24rem'
  var height = cfg.height || '40rem'
  var right = cfg.right || '1.5rem'
  var bottom = cfg.bottom || '1.5rem'

  var css =
    '#oa-agent-bubble-button{position:fixed;right:' + right + ';bottom:' + bottom + ';width:52px;height:52px;' +
    'border-radius:50%;border:0;background:' + color + ';color:#fff;cursor:pointer;z-index:2147483646;' +
    'box-shadow:0 4px 12px rgba(0,0,0,.25);font-size:24px;line-height:52px;padding:0}' +
    '#oa-agent-bubble-window{position:fixed;right:' + right + ';bottom:calc(' + bottom + ' + 64px);width:' + width +
    ';height:' + height + ';max-height:calc(100vh - 100px);max-width:calc(100vw - 2rem);background:#fff;' +
    'border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.25);z-index:2147483647;display:none;overflow:hidden;' +
    'flex-direction:column}' +
    '#oa-agent-bubble-window.oa-agent-open{display:flex}' +
    '#oa-agent-bubble-window .oa-agent-head{display:flex;align-items:center;justify-content:space-between;' +
    'padding:8px 12px;background:' + color + ';color:#fff;font:600 14px system-ui,"Microsoft YaHei",sans-serif}' +
    '#oa-agent-bubble-window .oa-agent-head button{background:transparent;border:0;color:#fff;cursor:pointer;' +
    'font-size:16px;margin-left:8px;padding:0 4px}' +
    '#oa-agent-bubble-window iframe{flex:1;width:100%;border:0}' +
    '@media (max-width:640px){#oa-agent-bubble-window{right:0;bottom:0;width:100vw;height:100vh;max-height:none;' +
    'max-width:none;border-radius:0}}'

  function el(tag, attrs, text) {
    var node = document.createElement(tag)
    for (var k in attrs) if (attrs.hasOwnProperty(k)) node.setAttribute(k, attrs[k])
    if (text) node.appendChild(document.createTextNode(text))
    return node
  }

  function launchUrl() {
    return cfg.hostUrl + (cfg.hostUrl.indexOf('?') >= 0 ? '&' : '?') + '_t=' + new Date().getTime()
  }

  function mount() {
    var style = el('style', { type: 'text/css' })
    if (style.styleSheet) style.styleSheet.cssText = css
    else style.appendChild(document.createTextNode(css))
    document.getElementsByTagName('head')[0].appendChild(style)

    var button = el('button', { id: 'oa-agent-bubble-button', type: 'button', title: title, 'aria-label': title }, '\uD83D\uDCAC')
    var win = el('div', { id: 'oa-agent-bubble-window', role: 'dialog', 'aria-label': title })
    var head = el('div', { 'class': 'oa-agent-head' })
    var actions = el('span', {})
    var reload = el('button', { type: 'button', title: '重新连接' }, '\u21BB')
    var close = el('button', { type: 'button', title: '关闭' }, '\u00D7')
    var frame = null

    head.appendChild(el('span', {}, title))
    actions.appendChild(reload)
    actions.appendChild(close)
    head.appendChild(actions)
    win.appendChild(head)

    function open() {
      if (!frame) {
        frame = el('iframe', { title: title, src: launchUrl() })
        win.appendChild(frame)
      }
      win.className = 'oa-agent-open'
    }
    function hide() {
      win.className = ''
    }

    button.onclick = function () {
      if (win.className === 'oa-agent-open') hide()
      else open()
    }
    close.onclick = hide
    reload.onclick = function () {
      if (frame) frame.src = launchUrl()
      else open()
    }

    document.body.appendChild(win)
    document.body.appendChild(button)
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount)
  else mount()
})()

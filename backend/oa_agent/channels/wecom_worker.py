"""企业微信长连接独立进程入口。

用法（在 backend 目录）::

    uv run python -m oa_agent.channels.wecom_worker

本进程会通过 AppRuntime 启动与 ``oa_agent.channels.wecom.WeComChannel`` 相同的长连接逻辑。
**同一企业微信机器人全局只能有一个有效 WebSocket consumer**；多实例部署时 API 与 worker
可分开，但请勿对同一 bot 同时跑多个 worker（或 API 内嵌 channel 与 worker 并存）。
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from oa_agent.runtime_state import NORMAL, AppRuntime
from oa_agent.settings import AppSettings

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    rt = AppRuntime(AppSettings())
    rt.boot()
    if rt.mode != NORMAL:
        log.error("系统未安装，无法启动企业微信 worker")
        return 1
    if rt.wecom is None:
        log.error("企业微信 channel 未初始化")
        return 1

    stop = False

    def _handle(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle)

    log.info("企业微信 worker 已运行（Ctrl+C 退出）；请确保同一 bot 仅有一个 consumer")
    try:
        while not stop:
            time.sleep(1)
    finally:
        rt.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

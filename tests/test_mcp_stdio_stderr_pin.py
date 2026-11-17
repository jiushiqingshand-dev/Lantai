"""MCP stdio 服务把 stderr 也钉成 UTF-8（票 30 A5 回归锁，Linux 上也能复现）。

背景：75a5ff95 / 33de2815 给 lantai.cli.mcp._configure_stdio_utf8 补了 stderr 和 fail-loud，
但 a737cdde（#50 解冲突，冲突文件统一取 master 版）把 mcp.py 回到了只钉 stdin/stdout
的旧版。tests/test_gate_probe_encoding.py 的三流探针只清掉 PYTHONIOENCODING，
靠宿主 locale 是 GBK/cp1252 才红；Linux CI 的 locale 本来就是 UTF-8，所以这个回退
在 GitHub CI 上一直是绿的，只有 Windows 上红。

这里用 PYTHONIOENCODING=latin-1 在任何平台上模拟「启动时标准流不是 UTF-8」，
再调真函数、真子进程，不 mock。
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _latin1_env() -> dict:
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    # 解释器启动建流时读这个变量：三股流都从 latin-1 起步（等价于非 UTF-8 的 Windows 宿主）
    env["PYTHONIOENCODING"] = "latin-1"
    env.setdefault("API_KEY", "test-key")
    return env


def _run(driver: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", driver],
        cwd=REPO,
        env=_latin1_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=180,
    )


def test_precondition_streams_start_non_utf8():
    """对照：不调函数时三股流确实是 latin-1，否则下面的断言是假绿。"""
    proc = _run(
        "import codecs, sys\n"
        "print(*(codecs.lookup(s.encoding).name for s in (sys.stdin, sys.stdout, sys.stderr)))\n"
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert proc.stdout.decode("ascii").split() == ["iso8859-1"] * 3


def test_configure_pins_stdout_and_stderr_from_non_utf8_start():
    driver = (
        "import sys\n"
        "from lantai.cli.mcp import _configure_stdio_utf8\n"
        "_configure_stdio_utf8()\n"
        "print(sys.stdin.encoding, sys.stdout.encoding, sys.stderr.encoding)\n"
    )
    proc = _run(driver)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")[-1500:]
    assert proc.stdout.decode("utf-8").split() == ["utf-8", "utf-8", "utf-8"]


def test_cjk_log_line_reaches_stderr_intact():
    """用户可见的后果：logger 往 stderr 写中文时不再出「--- Logging error ---」。"""
    driver = (
        "import logging, sys\n"
        "from lantai.cli.mcp import _configure_stdio_utf8\n"
        "_configure_stdio_utf8()\n"
        "h = logging.StreamHandler(sys.stderr)\n"
        "log = logging.getLogger('stderr_pin_probe')\n"
        "log.addHandler(h); log.propagate = False\n"
        "log.error('兰台检索失败：连接池上限')\n"
    )
    proc = _run(driver)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")[-1500:]
    err = proc.stderr.decode("utf-8", errors="replace")
    assert "Logging error" not in err, err[-1500:]
    assert "兰台检索失败：连接池上限" in err

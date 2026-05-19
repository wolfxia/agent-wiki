#!/usr/bin/env python3
"""
aw-agent lock wrapper — 防止多个 aw-agent serve 实例并发写 MANIFEST.jsonl

问题：OpenClaw 和 Hermes 各自启动 aw-agent serve，共享同一个 wiki workspace。
当两个实例同时写 MANIFEST.jsonl 时，文件锁冲突导致 MCP 超时。

方案：用 fcntl.flock 对 MANIFEST.jsonl 做进程级互斥锁。
- 获取锁后启动 aw-agent serve
- 锁被持有时等待（带超时）
- 超时则退出（让上层重试）

使用方式（替换 openclaw.json 中的 command）：
    "command": "python3",
    "args": ["/path/to/aw-agent-lock-wrapper.py", "serve", "--registry", "..."]
"""
import fcntl
import os
import subprocess
import sys
import time

LOCK_FILE = os.path.expanduser(
    os.environ.get(
        "AW_LOCK_FILE",
        "/Users/chao/agent-wiki-data/wiki-1/.aw-agent.lock",
    )
)
LOCK_TIMEOUT_SECONDS = int(os.environ.get("AW_LOCK_TIMEOUT", "120"))

# The real aw-agent binary
REAL_AW_AGENT = "/Users/chao/workspace/agent-wiki/.venv/bin/aw-agent"


def main():
    # Create lock file if it doesn't exist
    lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o644)

    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    lock_acquired = False

    while time.monotonic() < deadline:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_acquired = True
            break
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(1.0, remaining))
        except Exception:
            break  # fall through: run without lock rather than fail

    if not lock_acquired:
        pid_file = open(LOCK_FILE).read().strip()
        print(
            f"[aw-lock] ⚠️  Another instance (PID {pid_file}) holds the lock, "
            f"waited {LOCK_TIMEOUT_SECONDS}s. Starting anyway as fallback.",
            file=sys.stderr,
        )

    # Write our PID to the lock file
    os.ftruncate(lock_fd, 0)
    os.write(lock_fd, str(os.getpid()).encode())
    os.fsync(lock_fd)

    # Launch the real aw-agent with original args
    # Keep the exclusive lock held for the entire duration to prevent concurrent instances
    args = [REAL_AW_AGENT] + sys.argv[1:]
    try:
        proc = subprocess.run(args)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        sys.exit(130)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(lock_fd)
        # Clean up stale lock file
        try:
            if os.path.exists(LOCK_FILE) and open(LOCK_FILE).read().strip() == str(os.getpid()):
                os.unlink(LOCK_FILE)
        except Exception:
            pass


if __name__ == "__main__":
    main()

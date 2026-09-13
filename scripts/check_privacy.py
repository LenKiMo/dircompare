#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隐私检查：扫描仓库跟踪的文件中是否残留本机绝对路径等痕迹。

CI（每次 push/PR）与本地 pre-commit 钩子共用；命中即退出码 1。
用法:
    python scripts/check_privacy.py            # 扫描 git 跟踪的全部文件
    python scripts/check_privacy.py --staged   # 只扫描暂存区（pre-commit 用）
"""
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 每条：正则、说明。注意 (?!...) 负向断言避免误伤 https:// 这类正常文本。
PATTERNS = [
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"), "Windows 绝对路径（如 C:\\ 或 F:/）"),
    (re.compile(r"AppData[\\/](?:Local|Roaming)"), "Windows 用户配置目录"),
    (re.compile(r"C:[\\/]Users[\\/]"), "Windows 用户目录"),
    (re.compile(r"/home/[A-Za-z0-9_.-]+/"), "Linux 家目录"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/"), "macOS 家目录"),
    (re.compile(r"%LOCALAPPDATA%|%APPDATA%|%USERPROFILE%"), "本机环境变量路径"),
]

SKIP_FILES = {"scripts/check_privacy.py"}          # 本文件含规则字面量，跳过自身
SKIP_SUFFIX = (".ico", ".png", ".jpg", ".zip", ".exe", ".dll", ".pyc")


def tracked_files(staged):
    if staged:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                             capture_output=True, text=True, check=True).stdout
        return [p for p in out.splitlines() if p.strip()]
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def main():
    staged = "--staged" in sys.argv[1:]
    hits = []
    for path in tracked_files(staged):
        if path in SKIP_FILES or path.endswith(SKIP_SUFFIX):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for rx, desc in PATTERNS:
                        m = rx.search(line)
                        if m:
                            hits.append((path, lineno, desc, m.group(0)))
        except (OSError, UnicodeError):
            continue
    if hits:
        print("✘ 检测到可能的隐私痕迹（本机路径），请脱敏后再提交：")
        for path, lineno, desc, frag in hits:
            print(f"  {path}:{lineno}  [{desc}] 命中：{frag}")
        print("\n提示：改用相对路径或占位符（如『项目根目录』『示例目录A』）。")
        return 1
    print("✓ 隐私检查通过：未发现本机绝对路径痕迹")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 web/engine.js 注入 dircompare_web.html.tmpl，生成自包含的 dircompare_web.html"""
import os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
with open(os.path.join(HERE, "web", "engine.js"), encoding="utf-8") as f:
    engine = f.read()
with open(os.path.join(HERE, "web", "dircompare_web.html.tmpl"), encoding="utf-8") as f:
    tpl = f.read()

assert "/*__ENGINE__*/" in tpl, "模板缺少引擎占位符"
assert "__ENGINE__" not in engine, "引擎内容含占位符字样，冲突"
out = tpl.replace("/*__ENGINE__*/", engine)
dest = os.path.join(HERE, "dircompare_web.html")
with open(dest, "w", encoding="utf-8") as f:
    f.write(out)
print("已生成:", dest, f"({os.path.getsize(dest) / 1024:.1f} KB)")

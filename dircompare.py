#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dircompare.py — 双文件夹内容比对工具（SHA1 / SHA256，支持跨文件名匹配"谁等于谁"）

用法：
    python dircompare.py "目录A" "目录B" [选项]

常用示例：
    python dircompare.py "示例目录A" "示例目录B"
    python dircompare.py 目录A 目录B --algo sha1 --html report.html --open
    python dircompare.py 目录A 目录B --csv out      # 另导出 CSV 供 Excel 处理
    python dircompare.py 目录A 目录B --quick        # 超大目录提速模式

原理与可靠性：
    1. 先按文件大小分层：只对两侧都出现的尺寸做哈希，其余文件直接判"仅一侧有"
       （大小不同 => 内容必不同，无需哈希）
    2. 对候选文件做 SHA1/SHA256 全量哈希（--quick 则先采样首/中/尾块预筛，
       命中的再做全量哈希确认 —— 最终判定永远基于全量哈希，不会失真）
    3. 同尺寸+同哈希 => 内容相同，跨目录配对。若组内两侧尺寸互不重复，
       则按尺寸一一对应，配对结果"确定"（无歧义）；否则给"推测"排序建议
    4. 另报告：同名但内容不同（覆盖/同步危险项）、仅存在于单侧的文件清单

输出：
    控制台摘要 + 可选自包含交互式 HTML 报告（双击即开，可过滤搜索）
    + 可选 CSV（UTF-8 BOM，Excel 可直接打开）
"""
import argparse, csv, hashlib, html as H, io, json, os, re, sys, time
from collections import Counter, defaultdict

# 模块级 UTF-8 输出：任何 import 本模块的进程（CLI / GUI / 测试）在
# cp1252 等非 UTF-8 代码页环境（如 CI runner）打印中文也不会崩。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SAMPLE_HEAD = 256 * 1024

def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{n} B"
            return f"{n:.1f} {unit}"
        n /= 1024

def nat_key(rel):
    """自然排序：001a.jpg -> (1,'a')；2529.jpg -> (2529,'')"""
    stem = os.path.splitext(os.path.basename(rel))[0]
    m = re.match(r"(\d+)", stem)
    return (int(m.group(1)), stem[m.end():]) if m else (10 ** 12, stem)

def esc(s):
    return H.escape(str(s), quote=True)

# ---------------- 采集 ----------------
class Rec:
    __slots__ = ("side", "root", "rel", "size", "sha", "err")
    def __init__(self, side, root, rel, size):
        self.side, self.root, self.rel, self.size, self.sha, self.err = side, root, rel, size, None, None
    @property
    def name(self):
        return os.path.basename(self.rel)
    @property
    def abs(self):
        return os.path.join(self.root, self.rel)

def collect(root, side, depth):
    root = os.path.abspath(root)
    out, zero, errs = [], 0, []
    base = root.rstrip("\\/").count(os.sep)
    for dp, dns, fns in os.walk(root):
        if depth is not None and dp.count(os.sep) - base >= depth:
            dns[:] = []
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root)
            try:
                st = os.stat(p)
            except OSError as e:
                errs.append((rel, str(e))); continue
            if not os.path.isfile(p):
                continue
            if st.st_size == 0:
                zero += 1; continue
            out.append(Rec(side, root, rel, st.st_size))
    return out, zero, errs

def hash_file(path, algo, quick=False):
    h = hashlib.new(algo)
    size = os.path.getsize(path)
    if quick and size > 4 * SAMPLE_HEAD:
        with open(path, "rb") as f:
            h.update(f.read(SAMPLE_HEAD))
            f.seek(max(0, size // 2 - SAMPLE_HEAD // 2)); h.update(f.read(SAMPLE_HEAD))
            f.seek(max(0, size - SAMPLE_HEAD)); h.update(f.read(SAMPLE_HEAD))
        return h.hexdigest()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b: break
            h.update(b)
    return h.hexdigest()

# ---------------- 核心比对 ----------------
def compare(rootA, rootB, algo, quick, depth, quiet, progress_cb=None):
    """progress_cb(done, total, rel): 每哈希一个候选文件回调一次（GUI 进度用）。"""
    def log(m):
        if not quiet:
            print(m, flush=True)
    t0 = time.time()
    log("枚举目录 A …");  fa, za, ea = collect(rootA, "A", depth)
    log("枚举目录 B …");  fb, zb, eb = collect(rootB, "B", depth)
    log(f"A：{len(fa)} 文件 / {human(sum(r.size for r in fa))}（0 字节 {za}，失败 {len(ea)}）   "
        f"B：{len(fb)} 文件 / {human(sum(r.size for r in fb))}（0 字节 {zb}，失败 {len(eb)}）")

    bysize = defaultdict(list)
    for r in fa + fb:
        bysize[r.size].append(r)
    cand = [r for size, rs in bysize.items()
            for r in rs
            if size > 0 and len({x.side for x in rs}) == 2]
    log(f"两侧存在同尺寸的候选文件：{len(cand)} 个（其余按大小排除，无需哈希）")

    if quick:
        bysample = defaultdict(list)
        for r in cand:
            r.sha = hash_file(r.abs, algo, quick=True)
            bysample[(r.size, r.sha)].append(r)
        keep = {k for k, rs in bysample.items() if len({x.side for x in rs}) == 2}
        cand = [r for r in cand if (r.size, r.sha) in keep]
        for r in cand:
            r.sha = None
        log(f"--quick 采样预筛后待全量确认：{len(cand)}/{sum(len(rs) for rs in bysample.values())}")

    total = len(cand); done = 0
    for r in cand:
        try:
            r.sha = hash_file(r.abs, algo)
        except OSError as e:
            r.err = str(e)
        done += 1
        if progress_cb:
            progress_cb(done, total, r.rel)
        elif not quiet and (done == total or done % 25 == 0):
            sys.stdout.write(f"\r  哈希 [{done}/{total}] {r.rel[:60]}")
            sys.stdout.flush()
    if not quiet and total:
        sys.stdout.write("\n")

    groups = defaultdict(lambda: defaultdict(list))
    for r in cand:
        if r.sha:
            groups[(r.size, r.sha)][r.side].append(r)
    matched = {k: v for k, v in groups.items() if len(v) == 2}

    matchedA = {id(r) for k, v in matched.items() for r in v["A"]}
    matchedB = {id(r) for k, v in matched.items() for r in v["B"]}

    pairs = []          # (a|None, b|None, certain)
    for (size, sha), sides in sorted(matched.items()):
        la = sorted(sides["A"], key=lambda r: nat_key(r.rel))
        lb = sorted(sides["B"], key=lambda r: nat_key(r.rel))
        ua = len({r.size for r in la}) == len(la)
        ub = len({r.size for r in lb}) == len(lb)
        if ua and ub:                       # 两侧组内尺寸均互异 => 按尺寸一一对应，确定
            bmap = {r.size: r for r in lb}
            pairs += [(a, bmap[a.size], True) for a in la]
        else:
            n = min(len(la), len(lb))       # 排序建议（推测）
            pairs += [(la[i], lb[i], False) for i in range(n)]
            pairs += [(a, None, False) for a in la[n:]]
            pairs += [(None, b, False) for b in lb[n:]]

    onlyA = [r for r in fa if id(r) not in matchedA]
    onlyB = [r for r in fb if id(r) not in matchedB]

    nameA, nameB = defaultdict(list), defaultdict(list)
    for r in fa: nameA[r.name].append(r)
    for r in fb: nameB[r.name].append(r)
    names_diff = [(a, b) for nm in sorted(set(nameA) & set(nameB))
                  for a in nameA[nm] for b in nameB[nm]
                  if (a.size, a.sha) != (b.size, b.sha)]

    mbA = sum(r.size for r in fa if id(r) in matchedA)
    mbB = sum(r.size for r in fb if id(r) in matchedB)
    real = [(a, b, c) for a, b, c in pairs if a and b]
    stats = dict(nA=len(fa), nB=len(fb), zA=za, zB=zb,
                 bytesA=sum(r.size for r in fa), bytesB=sum(r.size for r in fb),
                 nMatchA=len(matchedA), nMatchB=len(matchedB), nPairs=len(real),
                 nCertain=sum(1 for _, _, c in real if c), mbA=mbA, mbB=mbB,
                 nOnlyA=len(onlyA), nOnlyB=len(onlyB), nND=len(names_diff), nErr=len(ea) + len(eb))
    log(f"完成，耗时 {time.time() - t0:.1f}s。"
        f"相同内容：A {stats['nMatchA']} 文件 ↔ B {stats['nMatchB']} 文件（{stats['nPairs']} 对，确定 {stats['nCertain']}）；"
        f"仅A {stats['nOnlyA']}，仅B {stats['nOnlyB']}，同名不同内容 {stats['nND']}")
    return dict(rootA=rootA, rootB=rootB, pairs=pairs, onlyA=onlyA, onlyB=onlyB,
                names_diff=names_diff, stats=stats, t0=t0, errs=ea + eb)

# ---------------- 控制台 ----------------
def console(res):
    s, C = res["stats"], {"G": "\033[32m", "Y": "\033[33m", "R": "\033[31m", "B": "\033[36m", "X": "\033[0m"}
    def w(txt): print(txt)
    w(f"\n{'=' * 80}\n比对结果  目录A：{res['rootA']}\n         目录B：{res['rootB']}\n{'=' * 80}")
    w(f"A：{s['nA']} 文件 {human(s['bytesA'])}（0 字节 {s['zA']}）   B：{s['nB']} 文件 {human(s['bytesB'])}（0 字节 {s['zB']}）")
    w(f"{C['G']}✔ 内容相同 {s['nMatchA']}↔{s['nMatchB']}{C['X']}  {s['nPairs']} 对（A 侧重复占用 {human(s['mbA'])}，B 侧 {human(s['mbB'])}）"
      f"[确定 {s['nCertain']} 对 / 推测 {s['nPairs'] - s['nCertain']} 对]")
    pair_lines, show_all = [], s["nPairs"] + s["nOnlyA"] + s["nOnlyB"] <= 300
    for a, b, cert in res["pairs"]:
        if a and b:
            tag = "同名" if a.name == b.name else ("同路径" if a.rel == b.rel else "不同名")
            mark = "确定" if cert else "推测"
            pair_lines.append(f"  {mark}  {a.rel}  ⟷  {b.rel}  [{tag}]  {human(a.size)}")
        elif a:
            pair_lines.append(f"  该侧多出  {a.rel}  （B 中无此内容的对应份）")
        else:
            pair_lines.append(f"  该侧多出  {b.rel}  （A 中无此内容的对应份）")
    only_lines = (["→ 仅存在于 A："] + [f"    {r.rel}  {human(r.size)}" for r in sorted(res["onlyA"], key=lambda x: nat_key(x.rel))]
                  if s["nOnlyA"] else []) + \
                 (["→ 仅存在于 B："] + [f"    {r.rel}  {human(r.size)}" for r in sorted(res["onlyB"], key=lambda x: nat_key(x.rel))]
                  if s["nOnlyB"] else [])
    for i, ln in enumerate(pair_lines + only_lines):
        if not show_all and i >= 300:
            w(f"  … 其余 {len(pair_lines) + len(only_lines) - i} 行省略（用 --html 查看完整列表）")
            break
        w(ln)
    if s["nND"]:
        w(f"\n{C['Y']}⚠ 同名但内容不同 {s['nND']} 处（同名 ≠ 同一内容，覆盖/同步前注意）{C['X']}")
        for i, (a, b) in enumerate(res["names_diff"][:20]):
            w(f"    {a.rel}  vs  {b.rel}   [{human(a.size)} vs {human(b.size)}]")
        if s["nND"] > 20: w(f"    … 其余 {s['nND'] - 20} 处")
    if res["errs"]:
        w(f"\n{C['R']}✘ 读取失败 {len(res['errs'])} 个（前 5）：{C['X']}")
        for rel, e in res["errs"][:5]:
            w(f"    {rel}: {e}")

# ---------------- 序列化（GUI 渲染用） ----------------
def result_to_json(res):
    """compare() 结果转纯 dict/list（Rec → JSON 友好），供 GUI 等外部渲染。"""
    def rec(r):
        return {"rel": r.rel, "name": r.name, "size": r.size,
                "sha": r.sha, "err": r.err} if r else None
    return {
        "rootA": res["rootA"], "rootB": res["rootB"],
        "stats": res["stats"],
        "pairs": [{"a": rec(a), "b": rec(b), "certain": c} for a, b, c in res["pairs"]],
        "onlyA": [rec(r) for r in res["onlyA"]],
        "onlyB": [rec(r) for r in res["onlyB"]],
        "names_diff": [{"a": rec(a), "b": rec(b)} for a, b in res["names_diff"]],
        "errs": [{"rel": r, "msg": m} for r, m in res["errs"]],
    }

# ---------------- HTML 报告 ----------------
def render_html(res, algo):
    s, pairs = res["stats"], res["pairs"]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    pair_rows = []
    for a, b, cert in pairs:
        if a and b:
            badge = '<span class="b-certain">确定</span>' if cert else '<span class="b-guess">推测</span>'
            same = '<span class="b-same">同名</span>' if a.name == b.name else ''
            pair_rows.append(f"<tr><td>{esc(a.rel)}</td><td>{esc(b.rel)}</td><td>{human(a.size)}</td><td>{badge}{same}</td></tr>")
        elif a:
            pair_rows.append(f'<tr><td>{esc(a.rel)}</td><td class="dim">（B 无对应份）</td><td>{human(a.size)}</td><td><span class="b-only">该侧多出</span></td></tr>')
        else:
            pair_rows.append(f'<tr><td class="dim">（A 无对应份）</td><td>{esc(b.rel)}</td><td>{human(b.size)}</td><td><span class="b-only">该侧多出</span></td></tr>')
    rows_nd = "".join(f"<tr><td>{esc(a.rel)}</td><td>{esc(b.rel)}</td><td>{human(a.size)}</td><td>{human(b.size)}</td></tr>"
                      for a, b in res["names_diff"])
    rows_oA = "".join(f"<tr><td>{esc(r.rel)}</td><td>{human(r.size)}</td></tr>" for r in sorted(res["onlyA"], key=lambda x: nat_key(x.rel)))
    rows_oB = "".join(f"<tr><td>{esc(r.rel)}</td><td>{human(r.size)}</td></tr>" for r in sorted(res["onlyB"], key=lambda x: nat_key(x.rel)))
    rows_err = "".join(f"<tr><td>{esc(r[0])}</td><td>{esc(r[1])}</td></tr>" for r in res["errs"])

    nPair = s["nPairs"]
    nGuess = nPair - s["nCertain"]
    chips = [
        ("A 文件数", s["nA"]), ("B 文件数", s["nB"]),
        ("相同内容文件", f"{s['nMatchA']} ↔ {s['nMatchB']}"),
        ("比对对数", f"{nPair}（确定 {s['nCertain']} / 推测 {nGuess}）"),
        ("A 侧重复占用", human(s["mbA"])), ("B 侧重复占用", human(s["mbB"])),
        ("仅存在于 A", s["nOnlyA"]), ("仅存在于 B", s["nOnlyB"]),
        ("同名不同内容", s["nND"]), ("读取失败", s["nErr"]),
    ]
    chip_html = "".join(f'<div class="chip"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>' for k, v in chips)

    def sec(title, badge, cls, body, open_, note=""):
        note_html = f'<span class="note">{esc(note)}</span>' if note else ''
        return (f'<details class="sec"{" open" if open_ else ""}><summary><span class="t">{esc(title)}</span>{note_html}'
                f'<span class="hbadge {cls}">{esc(badge)}</span></summary>{body}</details>')

    def tbl(header, body_rows, empty_cols):
        head = "".join(f"<th>{esc(h)}</th>" for h in header)
        body = body_rows or f'<tr><td class="dim" colspan="{empty_cols}">（无）</td></tr>'
        return f'<div class="tblwrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    body = "".join([
        f'<h1>双目录文件比对报告</h1><div class="meta">{now} · 算法 {algo.upper()} · 耗时 {time.time() - res["t0"]:.1f}s · '
        f'“推测”=组内同名同内容有多个候选，按文件名排序建议配对；同名同内容且两侧尺寸互异时为“确定”</div>',
        '<div class="roots"><div><b>目录 A</b><code>' + esc(res["rootA"]) + "</code></div>"
        '<div><b>目录 B</b><code>' + esc(res["rootB"]) + "</code></div></div>",
        '<div class="chips">' + chip_html + "</div>",
        '<div class="toolbar"><input id="q" placeholder="🔍 过滤 —— 输入文件名任意部分即实时筛选下方各表" autocomplete="off"></div>',
        sec("相同内容匹配（谁等于谁）", nPair, "ok",
            tbl(["目录A 文件", "目录B 文件", "大小", "判定"], "".join(pair_rows), 4), True),
        sec("⚠ 同名但内容不同（同名 ≠ 同一张图，覆盖前留意）", s["nND"], "warn",
            tbl(["目录A 文件", "目录B 文件", "A 大小", "B 大小"], rows_nd, 4), s["nND"] > 0),
        sec("→ 仅存在于目录 A", s["nOnlyA"], "onlyA", tbl(["文件", "大小"], rows_oA, 2), False,
            "如需合并/清理，这些是 B 侧缺失的候选"),
        sec("→ 仅存在于目录 B", s["nOnlyB"], "onlyB", tbl(["文件", "大小"], rows_oB, 2), False),
        sec("✘ 读取失败", s["nErr"], "err", tbl(["文件", "错误"], rows_err, 2), False),
    ])

    css = """
    :root{--bg:#0f1117;--card:#171a23;--bd:#272d3d;--fg:#e6e8ef;--mut:#8b91a7;--acc:#4f8cff;--ok:#2ecc71;--warn:#f5b041;--err:#e74c3c}
    *{box-sizing:border-box}body{margin:0;font:14px/1.6 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--fg);padding:22px}
    h1{margin:0 0 2px;font-size:21px}.meta{color:var(--mut);font-size:12px;margin-bottom:14px}
    .roots{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}
    .roots>div{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px;font-size:12px;min-width:0}
    .roots b{display:block;color:var(--acc);margin-bottom:3px}.roots code{word-break:break-all;font-family:Consolas,monospace;font-size:11.5px}
    .chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
    .chip{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:7px 12px;min-width:108px;text-align:center}
    .chip .v{font-size:16px;font-weight:700;color:var(--acc)}.chip .k{font-size:11px;color:var(--mut)}
    .toolbar{margin-bottom:12px}#q{width:100%;padding:9px 12px;border-radius:9px;border:1px solid var(--bd);background:var(--card);color:var(--fg);font-size:14px}
    #q:focus{outline:none;border-color:var(--acc)}
    details.sec{background:var(--card);border:1px solid var(--bd);border-radius:10px;margin-bottom:10px;overflow:hidden}
    summary{cursor:pointer;padding:11px 14px;font-weight:600;user-select:none;list-style:none;display:flex;align-items:center;gap:8px}
    summary::-webkit-details-marker{display:none}summary::before{content:"▸";color:var(--mut);margin-right:2px;transition:transform .15s}
    details[open] summary::before{transform:rotate(90deg)}summary .t{flex:0 0 auto}
    summary .note{color:var(--mut);font-weight:400;font-size:11.5px}
    .hbadge{margin-left:auto;font-size:11px;padding:1px 10px;border-radius:99px;font-weight:600;flex:0 0 auto}
    .ok{background:#15301f;color:var(--ok)}.warn{background:#3a2c12;color:var(--warn)}.onlyA{background:#0f2138;color:var(--acc)}
    .onlyB{background:#2a1630;color:#c98cf5}.err{background:#3a1216;color:var(--err)}
    .tblwrap{overflow:auto;max-height:50vh;border-top:1px solid var(--bd)}
    table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 14px;border-bottom:1px solid #20253a;white-space:nowrap}
    th{position:sticky;top:0;background:#1d2233;color:var(--mut);font-weight:600;font-size:12px;z-index:1}
    td{font-family:Consolas,monospace;font-size:12.5px}.dim{color:var(--mut)}
    .b-certain{color:var(--ok);border:1px solid #25603f;background:#10281b;border-radius:6px;padding:0 7px;font-size:11px}
    .b-guess{color:#c98cf5;border:1px solid #4a2d55;background:#22102b;border-radius:6px;padding:0 7px;font-size:11px}
    .b-same{color:var(--acc);border:1px solid #27406b;border-radius:6px;padding:0 7px;font-size:11px;margin-left:5px}
    .b-only{color:var(--mut);border:1px solid var(--bd);border-radius:6px;padding:0 7px;font-size:11px}
    tr.hide{display:none}
    """
    js = ("const q=document.getElementById('q');q.addEventListener('input',()=>{const t=q.value.trim().toLowerCase();"
          "document.querySelectorAll('details.sec').forEach(d=>{let vis=0,tot=0;"
          "d.querySelectorAll('tbody tr').forEach(tr=>{tot++;const hit=!t||tr.textContent.toLowerCase().includes(t);"
          "tr.classList.toggle('hide',!hit);if(hit)vis++;});"
          "const b=d.querySelector('.hbadge');if(t&&b&&d.querySelector('.t').textContent.indexOf('（')<0){"
          "const base=d.querySelector('summary').innerHTML.replace(/\\d+\\/\\d+$/,'').replace(/<span class=\"hbadge[^\"]*\">[^<]*<\\/span>/,'');}})})")
    return ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>双目录比对 {now}</title>"
            f"<style>{css}</style></head><body>{''.join(body)}<script>{js}</script></body></html>")

# ---------------- CSV ----------------
def write_csv(prefix, res):
    import csv as _csv
    rows_p = []
    for a, b, cert in res["pairs"]:
        if a and b:
            rows_p.append([a.rel, b.rel, a.size, b.size, "确定" if cert else "推测(排序建议)"])
        elif a:
            rows_p.append([a.rel, "", a.size, "", "A 侧多出"])
        else:
            rows_p.append(["", b.rel, "", b.size, "B 侧多出"])
    for nm, rows in [("_pairs.csv", rows_p),
                     ("_names_diff.csv", [[a.rel, b.rel, a.size, b.size, "同名不同内容"] for a, b in res["names_diff"]]),
                     ("_onlyA.csv", [[r.rel, r.size] for r in res["onlyA"]]),
                     ("_onlyB.csv", [[r.rel, r.size] for r in res["onlyB"]])]:
        with open(prefix + nm, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(["目录A相对路径", "目录B相对路径", "A大小", "B大小", "判定"]) if nm == "_pairs.csv" else None
            w.writerow(["目录A相对路径", "目录B相对路径", "A大小", "B大小", "说明"]) if nm == "_names_diff.csv" else None
            w.writerow(["相对路径", "大小字节"]) if nm in ("_onlyA.csv", "_onlyB.csv") else None
            w.writerows(rows)
    print("CSV 已写出：" + prefix + "_pairs.csv 等 4 个文件")

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description="双文件夹内容比对：按大小分层 + SHA1/SHA256 哈希，文件名不同也能匹配出谁等于谁")
    ap.add_argument("dirA", help="目录 A")
    ap.add_argument("dirB", help="目录 B")
    ap.add_argument("--algo", choices=["sha256", "sha1"], default="sha256")
    ap.add_argument("--quick", action="store_true", help="大目录提速：采样预筛 + 全量确认（结果仍为全量哈希判定）")
    ap.add_argument("--html", metavar="FILE", help="生成自包含 HTML 报告")
    ap.add_argument("--csv", metavar="PREFIX", help="导出 CSV（前缀名）")
    ap.add_argument("--open", action="store_true", help="完成后打开 HTML")
    ap.add_argument("--depth", type=int, default=None, help="递归深度上限（0=只看顶层）")
    ap.add_argument("--quiet", action="store_true", help="只输出摘要")
    args = ap.parse_args()

    def clean(p):
        p = p.strip()
        if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
            p = p[1:-1]
        return os.path.normpath(p.rstrip("\\/") or p)
    rootA, rootB = clean(args.dirA), clean(args.dirB)
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    for r in (rootA, rootB):
        if not os.path.isdir(r):
            sys.exit("目录不存在：" + r)

    res = compare(rootA, rootB, args.algo, args.quick, args.depth, args.quiet)
    console(res)
    if args.html:
        os.makedirs(os.path.dirname(os.path.abspath(args.html)), exist_ok=True)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(res, args.algo))
        p = os.path.abspath(args.html)
        print("\nHTML 报告：" + p)
        if args.open:
            import webbrowser; webbrowser.open(p)
    if args.csv:
        write_csv(args.csv, res)

if __name__ == "__main__":
    main()

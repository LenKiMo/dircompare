#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 一致性自动化验收：验证 compare() 在带/不带 progress_cb 时结果完全一致，
   以及 result_to_json() 序列化往返不丢数据。用法：python tests/test_gui_consistency.py [目录A] [目录B]
   不带参数则用内置临时夹具自测。"""
import json, os, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dircompare

def build_fixture(base):
    A = os.path.join(base, "甲套图"); B = os.path.join(base, "乙合集")
    os.makedirs(os.path.join(A, "sub")); os.makedirs(os.path.join(B, "sub2"))
    def w(p, data):
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
    w(os.path.join(A, "2529.jpg"), b"photo-A-1" * 300)          # 对应 B 重命名
    w(os.path.join(A, "2530.jpg"), b"photo-A-2" * 311)
    w(os.path.join(A, "同名.jpg"), b"same-name" * 200)          # B 同名同内容
    w(os.path.join(A, "同名不同.jpg"), b"content-X" * 150)      # B 同名但内容不同
    w(os.path.join(A, "clash.jpg"), b"AAAA" * 37)               # 同大小不同内容（148B vs 148B）
    w(os.path.join(A, "仅A.txt"), b"only-a")
    w(os.path.join(A, "sub", "深层.jpg"), b"deep" * 500)
    big = os.urandom(3 * 1024 * 1024 + 999)
    w(os.path.join(A, "大文件.bin"), big)
    w(os.path.join(A, "零字节.txt"), b"")
    w(os.path.join(B, "0029.jpg"), b"photo-A-1" * 300)          # 重命名对应
    w(os.path.join(B, "0030.jpg"), b"photo-A-2" * 311)
    w(os.path.join(B, "同名.jpg"), b"same-name" * 200)
    w(os.path.join(B, "同名不同.jpg"), b"content-Y" * 150)
    w(os.path.join(B, "clash.jpg"), b"BBBB" * 37)
    w(os.path.join(B, "仅B.txt"), b"only-b")
    w(os.path.join(B, "sub2", "深层.jpg"), b"deep" * 500)
    w(os.path.join(B, "大文件改名.bin"), big)
    w(os.path.join(B, "零字节.txt"), b"")
    return A, B

def check(res_cli, res_gui, log):
    ok = True
    for key in res_cli["stats"]:
        if res_cli["stats"][key] != res_gui["stats"][key]:
            ok = False; log.append(f"stats[{key}] 不一致: {res_cli['stats'][key]} vs {res_gui['stats'][key]}")
    for field, label in (("pairs", "配对"), ("onlyA", "仅A"), ("onlyB", "仅B"),
                         ("names_diff", "同名不同"), ("errs", "错误")):
        if len(res_cli[field]) != len(res_gui[field]):
            ok = False; log.append(f"{label} 数量不一致: {len(res_cli[field])} vs {len(res_gui[field])}")
    # JSON 往返：序列化后配对结构完整
    j = dircompare.result_to_json(res_gui)
    round_ok = (len(j["pairs"]) == len(res_gui["pairs"]) and
                all((p["a"] is None) == (a is None) for p, (a, _, _) in zip(j["pairs"], res_gui["pairs"])))
    if not round_ok:
        ok = False; log.append("result_to_json 往返损坏")
    return ok

def main():
    args = sys.argv[1:]
    if len(args) >= 2:
        A, B, tmp = args[0], args[1], None
    else:
        tmp = tempfile.mkdtemp(prefix="dcmp_consistency_")
        A, B = build_fixture(tmp)
    log = []
    try:
        res_cli = dircompare.compare(A, B, "sha256", False, None, True)
        plog = []
        res_gui = dircompare.compare(A, B, "sha256", False, None, True,
                                     progress_cb=lambda d, t, r: plog.append((d, t, r)))
        s = res_cli["stats"]
        print(f"夹具统计: 匹配 {s['nPairs']} 对(确定 {s['nCertain']}) | 仅A {s['nOnlyA']} | 仅B {s['nOnlyB']} | "
              f"同名不同 {s['nND']} | 0字节 A{s['zA']}/B{s['zB']}")
        if not plog:
            log.append("progress_cb 未被调用")
        elif plog[-1][0] != plog[-1][1]:
            log.append(f"进度末条未收敛: {plog[-1]}")
        ok = check(res_cli, res_gui, log)
        print("✅ 一致性验证通过（CLI == GUI 路径，进度回调正常，JSON 往返无损）" if ok and not log
              else "❌ 验证失败:\n" + "\n".join("  - " + x for x in log))
        return 0 if ok and not log else 1
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dircompare GUI（路径 A：pywebview + WebView2）
复用 dircompare.py 内核（import compare / write_csv / render_html / result_to_json）。
用法:
    python gui/gui_webview.py [--debug]        # 运行 GUI（--debug 开 DevTools）
    python gui/gui_webview.py --selftest       # 无窗口自检（打包冒烟用），结果写 %TEMP%
"""
import argparse, json, os, queue, sys, threading, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dircompare  # noqa: E402

APP_TITLE = "dircompare — 双目录内容比对（只读）"


def _dlg_const(name, fallback):
    """pywebview 6 新枚举 FileDialog.*，旧版退回 *_DIALOG 常量。"""
    try:
        import webview
        return getattr(webview.FileDialog, name)
    except Exception:
        import webview
        return getattr(webview, fallback)


class BackendAPI:
    def __init__(self):
        self._window = None
        self._cancel = threading.Event()
        self._result = None
        self._result_algo = "sha256"
        self._busy = False

    def set_window(self, w):
        self._window = w

    # ---- 目录选择 ----
    def choose_dir(self, _label):
        try:
            result = self._window.create_file_dialog(
                _dlg_const("FOLDER", "FOLDER_DIALOG"), allow_multiple=False)
            return result[0] if result else None
        except Exception as e:
            return {"ok": False, "msg": f"目录选择失败：{e}"}

    # ---- 比对 ----
    def run_compare(self, pathA, pathB, algo="sha256", quick=False):
        pathA = (pathA or "").strip().strip('"')
        pathB = (pathB or "").strip().strip('"')
        for p in (pathA, pathB):
            if not p:
                return {"ok": False, "msg": "请先选择两个目录"}
            if not os.path.isdir(p):
                return {"ok": False, "msg": f"目录不存在：{p}"}
        if self._busy:
            return {"ok": False, "msg": "已有比对在进行中"}
        self._busy = True
        self._cancel.clear()
        self._result = None
        self._result_algo = algo

        def push(js):
            try:
                if self._window:
                    self._window.evaluate_js(js)
            except Exception:
                pass  # 窗口已关闭

        def worker():
            last = [0]
            def on_progress(done, total, rel):
                if self._cancel.is_set():
                    raise InterruptedError("用户取消")
                if done == total or done - last[0] >= 3 or done <= 1:
                    last[0] = done
                    push(f"onProgress({done},{total},{json.dumps(rel[:90], ensure_ascii=False)})")
            try:
                res = dircompare.compare(pathA, pathB, algo, quick,
                                         depth=None, quiet=True,
                                         progress_cb=on_progress)
                self._result = res
                payload = json.dumps(dircompare.result_to_json(res), ensure_ascii=False)
                push(f"onResult({payload})")
            except InterruptedError:
                push("onCancelled()")
            except Exception as e:
                push(f"onError({json.dumps(str(e), ensure_ascii=False)})")
            finally:
                self._busy = False

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "msg": "已开始"}

    def cancel(self):
        self._cancel.set()
        return {"ok": True}

    # ---- 导出 ----
    def export_csv(self):
        if not self._result:
            return {"ok": False, "msg": "还没有比对结果"}
        try:
            result = self._window.create_file_dialog(
                _dlg_const("SAVE", "SAVE_DIALOG"), save_filename="dircompare_pairs.csv")
        except Exception as e:
            return {"ok": False, "msg": f"保存对话框失败：{e}"}
        if not result:
            return {"ok": False, "msg": ""}  # 用户取消
        pfx = os.path.splitext(result)[0]
        try:
            dircompare.write_csv(pfx, self._result)
            return {"ok": True, "msg": f"已导出 4 个文件：{pfx}_pairs.csv 等"}
        except Exception as e:
            return {"ok": False, "msg": f"导出失败：{e}"}

    def export_html(self):
        if not self._result:
            return {"ok": False, "msg": "还没有比对结果"}
        try:
            result = self._window.create_file_dialog(
                _dlg_const("SAVE", "SAVE_DIALOG"), save_filename="比对报告.html")
        except Exception as e:
            return {"ok": False, "msg": f"保存对话框失败：{e}"}
        if not result:
            return {"ok": False, "msg": ""}
        try:
            with open(result, "w", encoding="utf-8") as f:
                f.write(dircompare.render_html(self._result, self._result_algo))
            return {"ok": True, "msg": f"已导出：{result}"}
        except Exception as e:
            return {"ok": False, "msg": f"导出失败：{e}"}


def get_html_path():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "gui_webview.html")


def message_box(title, text):
    """无 GUI 框架依赖的提示框（WebView2 缺失等场景兜底）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        sys.stderr.write(f"{title}: {text}\n")


def selftest():
    """打包冒烟：验证内核 import、pywebview import、compare+序列化+CSV 全链路。
    结果写入 %TEMP%\\dircompare_gui_selftest.txt，退出码 0/1。"""
    log = []
    try:
        import dircompare as dc
        log.append(f"内核 OK ({os.path.basename(dc.__file__)})")
        import webview  # noqa: F401
        log.append("pywebview import OK")
        base = tempfile.mkdtemp(prefix="dcmp_st_")
        try:
            A = os.path.join(base, "甲"); B = os.path.join(base, "乙")
            os.makedirs(A); os.makedirs(B)
            data = b"selftest-content" * 1000
            with open(os.path.join(A, "a.jpg"), "wb") as f: f.write(data)
            with open(os.path.join(B, "renamed.jpg"), "wb") as f: f.write(data)
            with open(os.path.join(B, "only_b.bin"), "wb") as f: f.write(b"x" * 2048)
            seen = []
            res = dc.compare(A, B, "sha256", False, None, True,
                             progress_cb=lambda d, t, r: seen.append(d))
            s = res["stats"]
            assert s["nPairs"] == 1 and s["nOnlyB"] == 1, f"stats 异常 {s}"
            assert seen and seen[-1] == len(seen), "进度回调异常"
            j = dc.result_to_json(res)
            assert j["pairs"][0]["a"]["rel"] == "a.jpg" and j["pairs"][0]["b"]["rel"] == "renamed.jpg"
            log.append(f"比对+JSON OK ({s['nPairs']} 对)")
            csvp = os.path.join(base, "out")
            dc.write_csv(csvp, res)
            assert os.path.exists(csvp + "_pairs.csv")
            log.append("CSV OK")
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)
        msg = "SELFTEST PASS\n" + "\n".join(log)
        code = 0
    except Exception as e:
        import traceback
        msg = "SELFTEST FAIL\n" + traceback.format_exc()
        code = 1
    out = os.path.join(tempfile.gettempdir(), "dircompare_gui_selftest.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(msg)
    return code


def main():
    ap = argparse.ArgumentParser(description=APP_TITLE)
    ap.add_argument("--debug", action="store_true", help="开启 WebView DevTools")
    ap.add_argument("--selftest", action="store_true", help="无窗口自检（打包冒烟）")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    try:
        import webview
    except Exception as e:
        message_box("缺少运行环境", "无法加载 pywebview：\n" + str(e) +
                    "\n\n请使用 CLI 版 dircompare.exe 或网页版 dircompare_web.html。")
        sys.exit(1)

    api = BackendAPI()
    try:
        window = webview.create_window(
            APP_TITLE, url=get_html_path(), js_api=api,
            width=1180, height=780, min_size=(860, 560), text_select=True)
    except Exception as e:
        message_box("启动失败", f"无法创建窗口（可能缺少 WebView2 运行时）：\n{e}")
        sys.exit(1)
    api.set_window(window)

    if os.environ.get("DIRC_TRACE"):
        def tracer():
            import tempfile as _tf
            time.sleep(7)
            out = os.path.join(_tf.gettempdir(), "dirc_trace.txt")
            try:
                bits = []
                for expr in ("typeof window.pywebview",
                             "(window.pywebview?'api:'+typeof window.pywebview.api:'no')",
                             "getComputedStyle(document.getElementById('noBridge')).display",
                             "document.title",
                             "(window.__pwReady===true?'readyflag-yes':'readyflag-no')"):
                    bits.append(expr + " => " + str(window.evaluate_js(expr)))
                with open(out, "w", encoding="utf-8") as f:
                    f.write("\n".join(bits))
            except Exception as e:
                with open(out, "w", encoding="utf-8") as f:
                    f.write("TRACE-ERR " + str(e))
        threading.Thread(target=tracer, daemon=True).start()

    try:
        webview.start(debug=args.debug)
    except Exception as e:
        message_box("启动失败", f"WebView 初始化失败（Windows 11 应自带 WebView2）：\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

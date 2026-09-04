#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dircompare GUI — Tkinter 版（路径 B：纯标准库零依赖）
与 pywebview 版（gui_webview.py）并存；两者共用 dircompare.py 内核 compare()/write_csv()/render_html()。
特点：启动最快（无 WebView2/.NET）、免运行时依赖、Win7-11 全兼容。
用法:
    python gui/gui_tkinter.py              # 运行 GUI
    python gui/gui_tkinter.py --selftest   # 无窗口自检（打包冒烟），结果写 %TEMP%
"""
import argparse, ctypes, os, queue, sys, threading, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dircompare  # noqa: E402

APP_TITLE = "dircompare — 双目录内容比对（只读）"


def enable_windows_dpi_awareness():
    """在创建 Tk 窗口前启用 Windows 的最佳可用 DPI awareness。"""
    if sys.platform != "win32":
        return

    # 必须在 Tcl/Tk 初始化前调用；进程级 API 对 PyInstaller windowed
    # 进程同样生效。
    try:
        set_awareness = ctypes.windll.shcore.SetProcessDpiAwareness
        set_awareness.argtypes = [ctypes.c_int]
        set_awareness.restype = ctypes.c_long
        if set_awareness(2) == 0:  # PROCESS_PER_MONITOR_DPI_AWARE
            return
    except (AttributeError, OSError):
        pass

    # shcore 不可用或设置失败时，退回 system-DPI aware。
    try:
        set_system_awareness = ctypes.windll.user32.SetProcessDPIAware
        set_system_awareness.argtypes = []
        set_system_awareness.restype = ctypes.c_bool
        set_system_awareness()
    except (AttributeError, OSError):
        pass


def selftest():
    """与 gui_webview.py --selftest 相同的全链路自检（不依赖 Tk 窗口）。"""
    import shutil
    log = []
    try:
        base = tempfile.mkdtemp(prefix="dcmp_tk_st_")
        try:
            A = os.path.join(base, "甲"); B = os.path.join(base, "乙")
            os.makedirs(A); os.makedirs(B)
            data = b"selftest-content" * 1000
            with open(os.path.join(A, "a.jpg"), "wb") as f: f.write(data)
            with open(os.path.join(B, "renamed.jpg"), "wb") as f: f.write(data)
            with open(os.path.join(B, "only_b.bin"), "wb") as f: f.write(b"x" * 2048)
            seen = []
            res = dircompare.compare(A, B, "sha256", False, None, True,
                                     progress_cb=lambda d, t, r: seen.append(d))
            s = res["stats"]
            assert s["nPairs"] == 1 and s["nOnlyB"] == 1, f"stats 异常 {s}"
            assert seen and seen[-1] == len(seen), "进度回调异常"
            csvp = os.path.join(base, "out")
            dircompare.write_csv(csvp, res)
            assert os.path.exists(csvp + "_pairs.csv")
            log.append(f"比对+进度+JSON+CSV OK（{s['nPairs']} 对）")
        finally:
            shutil.rmtree(base, ignore_errors=True)
        msg, code = "SELFTEST PASS\n内核 OK\n" + "\n".join(log), 0
    except Exception:
        import traceback
        msg, code = "SELFTEST FAIL\n" + traceback.format_exc(), 1
    out = os.path.join(tempfile.gettempdir(), "dircompare_tk_selftest.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(msg)
    return code


class DirCompareGUI:
    COLORS = {"bg": "#0f1117", "card": "#171a23", "bd": "#272d3d", "fg": "#e6e8ef",
              "mut": "#8b91a7", "acc": "#4f8cff", "ok": "#2ecc71", "warn": "#f5b041",
              "sel": "#1d3461", "entry": "#1a1e2a"}
    FONT = ("Microsoft YaHei UI", 10)
    MONO = ("Consolas", 10)

    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1120x720")
        root.minsize(860, 540)
        self.pathA, self.pathB = tk.StringVar(), tk.StringVar()
        self.algo = tk.StringVar(value="sha256")
        self.quick = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar()
        self.q = queue.Queue()
        self.cancel_event = threading.Event()
        self.result = None
        self._all = {}          # tree -> [(iid, values)]
        self._style()
        self._icon()
        self._build()
        root.after(60, self._poll_queue)

    # ---------- 外观 ----------
    def _style(self):
        st = self.ttk.Style()
        self.root.configure(bg=self.COLORS["bg"])
        try:
            st.theme_use("clam")
        except Exception:
            pass
        C = self.COLORS
        st.configure(".", background=C["bg"], foreground=C["fg"], borderwidth=0,
                     focusthickness=0, font=self.FONT)
        st.configure("TFrame", background=C["bg"])
        st.configure("TLabel", background=C["bg"], foreground=C["fg"])
        st.configure("TLabelframe", background=C["bg"], bordercolor=C["bd"])
        st.configure("TLabelframe.Label", background=C["bg"], foreground=C["mut"])
        st.configure("TButton", background=C["card"], foreground=C["fg"],
                     bordercolor=C["bd"], borderwidth=1, padding=(14, 6))
        st.map("TButton", background=[("active", "#2b3550"), ("pressed", "#2b6de0")],
               bordercolor=[("active", C["acc"])])
        st.configure("Accent.TButton", background=C["acc"], foreground="#ffffff")
        st.map("Accent.TButton", background=[("active", "#3d7bf5"), ("disabled", C["card"])])

        # clam 会为 selected tab 应用额外的 padding/expand；显式覆盖
        # 这些状态映射，使所有状态保持相同的尺寸、字体和基线，选中只变色。
        tab_padding = "14 7"
        tab_expand = "0 0 0 0"
        st.configure("TNotebook", background=C["bg"], borderwidth=0,
                     tabmargins=(0, 0, 0, 0))
        st.configure("TNotebook.Tab", background=C["card"], foreground=C["fg"],
                     borderwidth=1, padding=tab_padding, font=self.FONT)
        st.map("TNotebook.Tab", background=[("selected", C["acc"]),
                                            ("active", "#2b3550")],
               foreground=[("selected", "#ffffff"), ("disabled", C["mut"])],
               bordercolor=[("selected", C["acc"]), ("active", C["acc"])],
               padding=[("selected", tab_padding), ("!selected", tab_padding)],
               expand=[("selected", tab_expand), ("!selected", tab_expand)])

        # 原生 downarrow 是黑色位图（clam），深色主题下不可见且布局黑盒
        # （贴顶/拉伸不可控）。方案：从 layout 移除它，改由 _attach_drop_arrow()
        # 在控件右缘 overlay 一个文本 "▼"（居中、颜色可控、系统字体抗锯齿）。
        try:
            cb_layout = st.layout("TCombobox")
            cb_layout = [n for n in cb_layout
                         if n[0].rsplit(".", 1)[-1] != "downarrow"]
            st.layout("TCombobox", cb_layout)
        except self.tk.TclError:
            pass
        st.configure("TCombobox", fieldbackground=C["entry"], foreground=C["fg"],
                     background=C["entry"], arrowcolor=C["fg"],
                     selectbackground=C["sel"], selectforeground=C["fg"],
                     insertcolor=C["fg"], padding=(4, 2))
        st.map("TCombobox", fieldbackground=[("readonly", C["entry"]),
                                              ("disabled", C["card"])],
               foreground=[("disabled", C["mut"])],
               arrowcolor=[("disabled", C["mut"]), ("active", "#ffffff")])
        st.configure("Treeview", background=C["card"], foreground=C["fg"],
                     fieldbackground=C["card"], borderwidth=0, rowheight=25,
                     font=self.MONO)
        st.configure("Treeview.Heading", background=C["bd"], foreground=C["mut"],
                     font=(self.FONT[0], 9, "bold"))
        st.map("Treeview", background=[("selected", C["sel"])])
        st.configure("Horizontal.TProgressbar", background=C["acc"],
                     troughcolor=C["bd"], borderwidth=0)
        st.configure("TEntry", fieldbackground=C["entry"], foreground=C["fg"],
                     insertcolor=C["fg"], bordercolor=C["bd"])
        st.configure("TCheckbutton", background=C["bg"], foreground=C["fg"])
        st.map("TCheckbutton", background=[("active", C["bg"])],
               foreground=[("disabled", C["mut"])])
        st.configure("Vertical.TScrollbar", background=C["bd"], troughcolor=C["bg"],
                     bordercolor=C["bg"], arrowcolor=C["fg"])
        st.configure("Horizontal.TScrollbar", background=C["bd"], troughcolor=C["bg"],
                     bordercolor=C["bg"], arrowcolor=C["fg"])
        self.style = st

        # 原生下拉弹出列表（popdown Listbox）默认白底黑字，与深色主题冲突；
        # 通过 option database 在 popdown 首次创建前预置深色配色。
        for opt, val in (("background", C["card"]), ("foreground", C["fg"]),
                         ("selectBackground", C["acc"]),
                         ("selectForeground", "#ffffff"),
                         ("font", self.MONO), ("borderWidth", 0),
                         ("highlightThickness", 0), ("relief", "flat")):
            self.root.option_add("*TCombobox*Listbox." + opt, val)
            self.root.option_add("*Combobox*Listbox." + opt, val)

    def _attach_drop_arrow(self, cb):
        """在 readonly Combobox 右缘 overlay 文本 ▼ 替代原生 downarrow。
        tk.Label 直接作为 cb 的子控件 place：rely=0.5 恒垂直居中、背景与
        field 同色无缝、字符经系统字体抗锯齿渲染。点击 ▼ 或框体弹出列表。"""
        def popup(_e=None):
            cb.focus_set()
            try:
                cb.event_generate("<Down>")
            except Exception:
                pass

        arrow = self.tk.Label(
            cb, text="▼", font=(self.FONT[0], 9), fg="#dfe3ee",
            bg=self.COLORS["entry"], cursor="hand2",
            bd=0, highlightthickness=0, padx=0, pady=0)
        arrow.bind("<Button-1>", popup)
        arrow.bind("<Enter>", lambda e: arrow.configure(fg="#9cc9ff"))
        arrow.bind("<Leave>", lambda e: arrow.configure(fg="#dfe3ee"))
        cb.bind("<Button-1>", popup)          # readonly：点框体任意处也弹
        arrow.place(relx=1.0, rely=0.5, anchor="e", x=-9)
        self._combo_arrow = arrow             # 防 GC

    def _icon(self):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        ico = os.path.join(base, "icon.ico")
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(ico)
            except Exception:
                pass

    # ---------- UI ----------
    def _build(self):
        tk, ttk = self.tk, self.ttk
        C = self.COLORS
        wrap = ttk.Frame(self.root)
        wrap.pack(fill="both", expand=True, padx=14, pady=(10, 8))

        # 标题行
        head = ttk.Frame(wrap); head.pack(fill="x")
        ttk.Label(head, text="双目录文件比对", font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        ttk.Label(head, text="Tk 版（零依赖）", foreground=C["mut"],
                  font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(8, 0))
        ttk.Label(head, text="⚡ 只读工具 — 不会修改任何文件", foreground=C["ok"],
                  font=("Microsoft YaHei UI", 9)).pack(side="right")

        # 目录选择
        dirs = ttk.Frame(wrap); dirs.pack(fill="x", pady=(8, 0))
        for col, (tag, var) in enumerate((("A", self.pathA), ("B", self.pathB))):
            f = ttk.Frame(dirs)
            f.grid(row=0, column=col, sticky="ew", padx=(0, 8) if col == 0 else 0)
            row1 = ttk.Frame(f); row1.pack(fill="x")
            ttk.Label(row1, text=f"目录 {tag}", foreground=C["acc"],
                      font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
            e = ttk.Entry(f, textvariable=var, font=self.MONO)
            e.pack(fill="x", pady=(3, 0))
            ttk.Button(f, text="浏览…", command=lambda v=var: self._pick(v)).pack(anchor="e", pady=(3, 0))
        dirs.columnconfigure(0, weight=1); dirs.columnconfigure(1, weight=1)

        # 工具栏
        tb = ttk.Frame(wrap); tb.pack(fill="x", pady=(8, 0))
        ttk.Label(tb, text="算法:").pack(side="left")
        cb = ttk.Combobox(tb, textvariable=self.algo, values=["sha256", "sha1"],
                          state="readonly", width=10)
        cb.pack(side="left", padx=(4, 10))
        self._attach_drop_arrow(cb)   # overlay ▼ 箭头（原生 downarrow 已在 layout 移除）
        ttk.Checkbutton(tb, text="quick 提速", variable=self.quick).pack(side="left")
        self.btn_start = ttk.Button(tb, text="▶ 开始比对", style="Accent.TButton",
                                    command=self._start)
        self.btn_start.pack(side="left", padx=(14, 6))
        self.btn_cancel = ttk.Button(tb, text="■ 取消", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(0, 14))
        self.btn_csv = ttk.Button(tb, text="导出 CSV", command=self._export_csv, state="disabled")
        self.btn_csv.pack(side="left", padx=(0, 6))
        self.btn_html = ttk.Button(tb, text="导出 HTML 报告", command=self._export_html,
                                   state="disabled")
        self.btn_html.pack(side="left")

        # 进度
        pf = ttk.Frame(wrap); pf.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(pf, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.progress_label = ttk.Label(pf, text="", foreground=C["mut"], font=self.MONO)
        self.progress_label.pack(anchor="w", pady=(2, 0))
        self.summary_label = ttk.Label(pf, text="", foreground=C["ok"])
        self.summary_label.pack(anchor="w")

        # 搜索
        sf = ttk.Frame(wrap); sf.pack(fill="x", pady=(6, 0))
        ttk.Label(sf, text="🔍").pack(side="left")
        self.search_var.trace_add("write", lambda *_: self._filter())
        e = ttk.Entry(sf, textvariable=self.search_var)
        e.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Label(sf, text="双击行复制路径", foreground=C["mut"]).pack(side="right", padx=(6, 0))

        # 选项卡表格
        nb = ttk.Notebook(wrap)
        nb.pack(fill="both", expand=True, pady=(6, 0))
        self.trees = {}
        for tab, cols in (("匹配配对", ("目录A 文件", "目录B 文件", "大小", "判定")),
                          ("仅存在于 A", ("文件", "大小")),
                          ("仅存在于 B", ("文件", "大小")),
                          ("同名不同内容", ("目录A 文件", "目录B 文件", "A 大小", "B 大小")),
                          ("读取失败", ("文件", "错误信息"))):
            frame = ttk.Frame(nb)
            tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
            widths = (330, 330, 90, 110) if len(cols) == 4 else (560, 100)
            for c, w in zip(cols, widths):
                tree.heading(c, text=c)
                tree.column(c, width=w, minwidth=60, anchor="w")
            vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")
            frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
            tree.bind("<Double-1>", lambda ev, t=tree: self._copy_row(ev, t))
            nb.add(frame, text=tab)
            self.trees[tab] = tree

    # ---------- 行为 ----------
    def _pick(self, var):
        from tkinter import filedialog
        p = filedialog.askdirectory(title="选择目录")
        if p:
            var.set(os.path.normpath(p))

    def _start(self):
        a, b = self.pathA.get().strip(), self.pathB.get().strip()
        if not a or not b:
            self._msg("请先选择两个目录"); return
        for p in (a, b):
            if not os.path.isdir(p):
                self._msg(f"目录不存在：{p}"); return
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_csv.configure(state="disabled"); self.btn_html.configure(state="disabled")
        self.summary_label.configure(text="")
        self.progress["value"] = 0
        self.progress_label.configure(text="准备中…")
        for t in self.trees.values():
            t.delete(*t.get_children())
        self._all = {}
        self.cancel_event.clear()
        self.result = None
        algo, quick = self.algo.get(), self.quick.get()

        def worker():
            def on_progress(done, total, rel):
                if self.cancel_event.is_set():
                    raise InterruptedError("用户取消")
                self.q.put(("progress", done, total, rel))
            try:
                res = dircompare.compare(a, b, algo, quick, None, True, progress_cb=on_progress)
                self.q.put(("done", res))
            except InterruptedError:
                self.q.put(("cancelled",))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _cancel(self):
        self.cancel_event.set()

    def _poll_queue(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "progress":
                    _, done, total, rel = m
                    if total:
                        self.progress.configure(maximum=total, value=done)
                    self.progress_label.configure(text=f"哈希计算 [{done}/{total}] {rel[:80]}")
                elif m[0] == "done":
                    self.result = m[1]
                    self._render(m[1])
                    self._finish(ok=True)
                elif m[0] == "cancelled":
                    self.progress_label.configure(text="已取消")
                    self._finish(ok=False)
                elif m[0] == "error":
                    self.progress_label.configure(text="")
                    self._msg("比对出错：" + m[1])
                    self._finish(ok=False)
        except queue.Empty:
            pass
        self.root.after(60, self._poll_queue)

    def _finish(self, ok=True):
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.btn_csv.configure(state="normal" if ok and self.result else "disabled")
        self.btn_html.configure(state="normal" if ok and self.result else "disabled")

    def _render(self, res):
        s = res["stats"]
        human = dircompare.human
        nat = dircompare.nat_key
        t = self.trees["匹配配对"]
        for a, b, cert in res["pairs"]:
            if a and b:
                tag = ("确定" if cert else "推测") + ("  [同名]" if a.name == b.name else "")
                t.insert("", "end", values=(a.rel, b.rel, human(a.size), tag))
            elif a:
                t.insert("", "end", values=(a.rel, "（B 无对应份）", human(a.size), "该侧多出"))
            else:
                t.insert("", "end", values=("（A 无对应份）", b.rel, human(b.size), "该侧多出"))
        for tab, items, mk in (("仅存在于 A", res["onlyA"],
                                lambda r: (r.rel, human(r.size))),
                               ("仅存在于 B", res["onlyB"],
                                lambda r: (r.rel, human(r.size)))):
            tr = self.trees[tab]
            for r in sorted(items, key=lambda x: nat(x.rel)):
                tr.insert("", "end", values=mk(r))
        tr = self.trees["同名不同内容"]
        for a, b in res["names_diff"]:
            tr.insert("", "end", values=(a.rel, b.rel, human(a.size), human(b.size)))
        tr = self.trees["读取失败"]
        for rel, msg in res["errs"]:
            tr.insert("", "end", values=(rel, msg))
        self.summary_label.configure(
            text=f"完成 · 相同内容 {s['nMatchA']}↔{s['nMatchB']}（{s['nPairs']} 对，"
                 f"确定 {s['nCertain']}） · 仅A {s['nOnlyA']} · 仅B {s['nOnlyB']} · "
                 f"同名不同 {s['nND']} · 0字节 A{s['zA']}/B{s['zB']} · 错误 {s['nErr']}")

    def _filter(self):
        term = self.search_var.get().strip().lower()
        for name, tree in self.trees.items():
            if name not in self._all:
                self._all[name] = [(iid, tree.item(iid)["values"]) for iid in tree.get_children()]
            tree.delete(*tree.get_children())
            for iid, vals in self._all[name]:
                text = " ".join(str(v) for v in vals).lower()
                if not term or term in text:
                    tree.insert("", "end", iid=iid, values=vals)

    def _copy_row(self, _ev, tree):
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0])["values"]
        if vals:
            txt = str(vals[0])
            self.root.clipboard_clear()
            self.root.clipboard_append(txt)
            self.progress_label.configure(text=f"已复制：{txt[:90]}")

    def _msg(self, text, kind="warning"):
        from tkinter import messagebox
        if kind == "warning":
            messagebox.showwarning("提示", text)
        else:
            messagebox.showerror("错误", text)

    def _export_csv(self):
        if not self.result:
            return
        from tkinter import filedialog, messagebox
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")],
                                         initialfile="dircompare_pairs.csv")
        if not p:
            return
        pfx = os.path.splitext(p)[0]
        try:
            dircompare.write_csv(pfx, self.result)
            messagebox.showinfo("导出完成", f"已导出：{pfx}_pairs.csv 等 4 个文件")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _export_html(self):
        if not self.result:
            return
        from tkinter import filedialog, messagebox
        p = filedialog.asksaveasfilename(defaultextension=".html",
                                         filetypes=[("HTML", "*.html")],
                                         initialfile="比对报告.html")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(dircompare.render_html(self.result, self.algo.get()))
            messagebox.showinfo("导出完成", f"已导出：{p}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


def main():
    enable_windows_dpi_awareness()
    ap = argparse.ArgumentParser(description=APP_TITLE + "（Tkinter 版）")
    ap.add_argument("--selftest", action="store_true", help="无窗口自检（打包冒烟）")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()          # 先隐藏，避免初始化失败时闪窗
        DirCompareGUI(root)
        root.deiconify()
        root.mainloop()
    except Exception as e:
        try:
            root.destroy()
        except Exception:
            pass
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, f"启动失败：{e}", APP_TITLE, 0x10)


if __name__ == "__main__":
    main()

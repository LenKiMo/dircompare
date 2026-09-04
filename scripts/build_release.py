#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dircompare 发布构建脚本（本地与 GitHub Actions 共用）。

用法:
    python scripts/build_release.py --version 0.1.0 [--out dist_release]

产物（Windows）:
    dircompare-<ver>-windows-cli.exe             CLI（onefile console，免 Python 命令行）
    dircompare-<ver>-windows-gui-webview.zip      GUI·WebView 版（onedir 目录，解压即用）
    dircompare-<ver>-windows-gui-tk.zip           GUI·Tk 版（onedir 目录，零运行时依赖）
    dircompare-<ver>-webpage.html                 网页版单文件
    SHA256SUMS.txt                                全部产物校验和
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, **kw):
    print(">>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def make_version_file(version, dest):
    """生成 PyInstaller --version-file 所需的 VSVersionInfo 文本。"""
    parts = version.split(".")
    while len(parts) < 4:
        parts.append("0")
    ver4 = ", ".join(parts[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({ver4}),
    prodvers=({ver4}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'LenKiMo'),
          StringStruct('FileDescription', 'DirCompare - dual-directory content compare ({version})'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'dircompare'),
          StringStruct('OriginalFilename', 'dircompare'),
          StringStruct('ProductName', 'DirCompare'),
          StringStruct('ProductVersion', '{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    return dest


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_dir(src_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src_dir):
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.relpath(full, os.path.dirname(src_dir))
                z.write(full, arc)


def smoke_test_cli(exe):
    """CLI 冒烟：对两个临时小目录跑一次比对，期望 exit 0。"""
    import tempfile
    base = tempfile.mkdtemp(prefix="dcmp_smoke_")
    try:
        a = os.path.join(base, "a"); b = os.path.join(base, "b")
        os.makedirs(a); os.makedirs(b)
        data = b"release-smoke" * 100
        for n, d in (("x.jpg", a), ("y.jpg", b)):
            with open(os.path.join(d, n), "wb") as f:
                f.write(data)
        with open(os.path.join(b, "only.txt"), "wb") as f:
            f.write(b"only-b-side")
        r = subprocess.run([exe, a, b, "--quiet"], capture_output=True, timeout=300)
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[:500]
        return True
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="如 0.1.0")
    ap.add_argument("--out", default="dist_release")
    ap.add_argument("--skip-webpage", action="store_true")
    args = ap.parse_args()
    ver = args.version
    out = os.path.join(ROOT, args.out)
    build = os.path.join(ROOT, "build")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)

    vinfo = make_version_file(ver, os.path.join(build, "version_info.txt"))
    common = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
              "--distpath", "dist_build", "--workpath", "build", "--specpath", "build",
              "--version-file", vinfo]

    # 1) CLI（onefile console）
    run(common + ["--onefile", "--console", "--name", "dircompare", "dircompare.py"])
    cli_exe = os.path.join(ROOT, "dist_build", "dircompare.exe")
    assert os.path.isfile(cli_exe)

    # 2) GUI·WebView 版（onedir windowed）
    run(common + ["--onedir", "--windowed", "--name", "dircompare_gui",
                  "--icon", os.path.join(ROOT, "gui", "icon.ico"),
                  "--add-data", os.path.join(ROOT, "gui", "gui_webview.html") + ";.",
                  "--hidden-import", "webview.platforms.winforms",
                  "gui/gui_webview.py"])

    # 3) GUI·Tk 版（onedir windowed，纯标准库）
    run(common + ["--onedir", "--windowed", "--name", "dircompare_gui_tk",
                  "--icon", os.path.join(ROOT, "gui", "icon.ico"),
                  "--add-data", os.path.join(ROOT, "gui", "icon.ico") + ";.",
                  "gui/gui_tkinter.py"])

    # ---- 汇总产物 ----
    prefix = f"dircompare-{ver}-windows"
    art_cli = os.path.join(out, prefix + "-cli.exe")
    shutil.copyfile(cli_exe, art_cli)

    art_wv = os.path.join(out, prefix + "-gui-webview.zip")
    zip_dir(os.path.join(ROOT, "dist_build", "dircompare_gui"), art_wv)

    art_tk = os.path.join(out, prefix + "-gui-tk.zip")
    zip_dir(os.path.join(ROOT, "dist_build", "dircompare_gui_tk"), art_tk)

    arts = [art_cli, art_wv, art_tk]
    if not args.skip_webpage:
        art_html = os.path.join(out, prefix + "-webpage.html")
        shutil.copyfile(os.path.join(ROOT, "dircompare_web.html"), art_html)
        arts.append(art_html)

    # ---- 校验和 ----
    sums = os.path.join(out, "SHA256SUMS.txt")
    with open(sums, "w", encoding="utf-8") as f:
        for p in arts:
            f.write(f"{sha256_of(p)}  {os.path.basename(p)}\n")

    # ---- 冒烟：GUI 两版 --selftest、CLI 实跑 ----
    import tempfile
    st_files = []
    for exe_name, label in (("dircompare_gui", "GUI-WebView"),
                            ("dircompare_gui_tk", "GUI-Tk")):
        exe = os.path.join(ROOT, "dist_build", exe_name, exe_name + ".exe")
        st = os.path.join(tempfile.gettempdir(),
                          "dircompare_%s_selftest.txt" % ("gui" if exe_name == "dircompare_gui" else "tk"))
        if os.path.exists(st):
            os.remove(st)
        subprocess.run([exe, "--selftest"], timeout=300)
        with open(st, encoding="utf-8") as f:
            assert "SELFTEST PASS" in f.read(), f"{label} selftest 未通过"
        print(f"smoke OK: {label}", flush=True)
    assert smoke_test_cli(art_cli), "CLI smoke 失败"
    print("smoke OK: CLI", flush=True)

    shutil.rmtree(os.path.join(ROOT, "dist_build"), ignore_errors=True)
    print("\n发布产物：", out)
    for f in sorted(os.listdir(out)):
        print("  -", f, f"({os.path.getsize(os.path.join(out, f)) / 1e6:.1f} MB)" if not f.endswith((".txt", ".html")) else "")


if __name__ == "__main__":
    main()

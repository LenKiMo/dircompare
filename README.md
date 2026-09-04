# 📂 DirCompare — 双文件夹内容比对

> 比对两个文件夹里的文件是否相同（SHA-1 / SHA-256）；**文件名不同也能匹配出「谁等于谁」**。
> 纯本地运行、**只读不删改**任何文件。

![GitHub Release](https://img.shields.io/github/v/release/LenKiMo/dircompare?style=flat-square&label=Release)
![Build](https://img.shields.io/github/actions/workflow/status/LenKiMo/dircompare/build-and-release.yml?style=flat-square&label=CI)
![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=flat-square)

---

## 📖 目录

- [这是什么](#-这是什么)
- [典型场景](#-典型场景)
- [运行形态与产物区别](#-运行形态与产物区别)
- [快速开始](#-快速开始)
- [界面预览功能](#-界面预览功能)
- [判定逻辑：确定 vs 推测](#-判定逻辑确定-vs-推测)
- [从源码运行](#-从源码运行)
- [自行打包](#-自行打包)
- [版本与自动构建](#-版本与自动构建)
- [测试](#-测试)
- [隐私与安全](#-隐私与安全)
- [许可证](#-许可证)

---

## 🤔 这是什么

DirCompare 逐文件比较两个目录的内容：先按**文件大小分层**（只哈希两侧都出现的尺寸，大图库可省 90%+ 读取），
再对候选做 **SHA-256 / SHA-1 全量哈希**，同尺寸 + 同哈希 ⇒ 内容相同，跨目录配对出**一一对应关系**——
即使两侧文件名完全不同（例如 `2529.jpg` 对 `001.jpg`）。

工具**只读取文件**，绝不移动、删除、改名任何文件，结果仅供你决策。

## 🎯 典型场景

- 比对一个独立图集文件夹与「合集压缩包解压后的同名子文件夹」，在文件名被重编过的情况下找出重复内容，以便删除某一侧、回收空间；
- 下载/备份后校验两个目录内容是否一致；
- 找出「仅存在于 A / 仅存在于 B」的文件，辅助合并目录。

## 📦 运行形态与产物区别

每次 Release 提供四种 Windows 产物（见 [版本与自动构建](#-版本与自动构建)），按需取用：

| 产物 | 形态 | 运行依赖 | 启动速度 | 界面 | 适用 |
|---|---|---|---|---|---|
| `...-windows-cli.exe` | 单文件 exe | 无 | 最快 | 命令行 | 脚本化、批量、远程 |
| `...-windows-gui-webview.zip` | 目录（onedir） | **WebView2**（Win11 自带；Win10 需装运行时） | 约 2s | 现代深色网页 UI | 日常图形界面（推荐） |
| `...-windows-gui-tk.zip` | 目录（onedir） | **无**（纯标准库，Win7-11） | 约 1.5-3s | 原生控件深色 UI | 无 WebView2 的环境 |
| `...-webpage.html` | 单文件网页 | 浏览器（Chrome/Edge/Brave） | 即开 | 网页 | 免安装、拖拽即比 |

**zip 版使用**：解压后运行其中的 `dircompare_gui.exe` 或 `dircompare_gui_tk.exe`（整个目录需保持完整，可给 exe 建桌面快捷方式）。

**两个 GUI 的区别**：两者功能完全一致（同一份比对内核、同样的目录选择/进度/表格/导出），仅界面技术不同——
WebView 版观感现代细腻（WebView2 渲染，Win11 自带）；Tk 版零运行时依赖、观感朴素但最轻、老系统也能跑。

## 🚀 快速开始

以两个真实目录为例（示例路径，请替换为你的目录）：

```bat
:: 命令行版
dircompare.exe "D:\我的图集A\套图一" "D:\我的图集B\合集解压\套图一" --html 报告.html --open

:: GUI 版：双击 exe → 点选/拖入两个目录 → 「开始比对」
```

输出会告诉你：哪些文件**内容相同**（谁等于谁）、哪些**仅存在于 A / 仅存在于 B**、
哪些**同名但内容不同**（⚠ 覆盖/同步前需警惕），以及删除某一侧可回收的空间。

## 🖥️ 界面预览功能

- 两种哈希算法可选（SHA-256 / SHA-1）+ quick 提速（采样预筛 + 全量确认，结果不失真）
- 实时逐文件进度，**可取消**
- 结果表格分栏：匹配配对 / 仅存在于 A / 仅存在于 B / 同名不同内容 / 读取失败
- 搜索过滤、双击单元格复制路径、统计卡片（重复占用空间等）
- 导出：CSV（4 个文件）/ 自包含 HTML 报告
- 网页版：把两个文件夹分别**拖进 A/B 区域**即比，纯浏览器本地计算，不上传

## 🧭 判定逻辑：确定 vs 推测

- **确定**：某哈希组内两侧文件尺寸互不重复，按尺寸一一锁定——配对无歧义（绝大多数场景）。
- **推测**：同内容在某一侧有多份（如 A 存了两张一模一样的图、B 只存一张），无法从内容区分谁对应谁，
  按文件名自然排序给出建议配对，仅供参考。

## ▶️ 从源码运行

```bash
# Python 3.11，仅标准库即可跑 CLI / Tk GUI / 网页版构建
python dircompare.py "目录A" "目录B" --html 报告.html      # CLI
python gui/gui_tkinter.py                                   # Tk GUI
python gui/gui_webview.py                                   # WebView GUI（需 pip install pywebview）

# 网页版：目录里直接双击 dircompare_web.html 即可；改 UI 后重新生成：
python web/build_web.py
```

## 🔨 自行打包

```bash
python -m pip install pyinstaller pywebview   # 打包 WebView 版才需要 pywebview
python scripts/build_release.py --version 0.1.0
# 产物输出到 dist_release/，含 SHA256SUMS.txt
```

## 🏷️ 版本与自动构建

- 版本号遵循 **SemVer**（`v主.次.修订`），通过 **Git tag** 管理，如 `v0.1.0`。
- **GitHub Actions 自动构建**：向仓库推送 `v*` 格式的 tag 后，CI 会在 Windows runner 上
  自动跑完整测试 → 构建上文全部四种产物 → 校验和 → 挂到对应 **Release** 页（含自动生成的更新说明）。
- `main` 分支每次提交也会跑测试与语法检查（不构建产物）；页面右上角也可**手动触发**构建（不发布）。
- 版本变更请保持 tag 与 Release notes 同步，例如：`git tag v0.1.0 && git push origin v0.1.0`。

## ✅ 测试

- `tests/test_gui_consistency.py`：验证 GUI 与 CLI 走的是**同一份 `compare()` 内核**，
  带/不带进度回调的结果逐字段一致（边界夹具：重命名、同名不同内容、同大小不同内容、大文件、0 字节等）。
- CLI、WebView、Tk 三份代码各有 `--selftest` 无窗口自检（写入 `%TEMP%` 供 CI 断言）。
- 网页版 JS 引擎与 Python 内核逻辑一一对应，由同一夹具互验。

## 🔒 隐私与安全

- **只读承诺**：除你主动点「导出 CSV / HTML」外，程序不写任何文件、不改动任何被比对目录。
- 全程本地运行：CLI/GUI 不上传数据；网页版由浏览器本地计算，同样不联网。
- 比对基于哈希内容，不读取图片/文件的可视内容。

## 🤖 AIGC 声明

本项目由人类作者规划与验收，代码与文档在开发过程中**使用了 AI 编程助手辅助生成**，
并经人工审查、测试后发布。比对结果正确性以测试夹具与源码为准。

## 📄 许可证

[MIT](LICENSE) © LenKiMo

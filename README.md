# A 系列 9288 翻译器

[![CI](https://github.com/HelloClyde/a-series-9288-translator/actions/workflows/build.yml/badge.svg)](https://github.com/HelloClyde/a-series-9288-translator/actions/workflows/build.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

把 A 系列 C6502 `.gam` 游戏在 **PC 上离线翻译为 BBK 9288 的 S1C33 原生程序**，
封装为安装在“娱乐”分类中的独立 KF2 EXE。提供 Windows 图形界面和命令行工具。

> 当前是实验性编译器，不是“任意 GAM 均兼容”的成品。编译成功不代表全流程或
> 真机性能已经验证。输出不是 Windows EXE，也不是携带游戏的播放器。

## 功能

- 选择 GAM，查看标题、体积与入口；设置程序名称和图标。
- 40×40 / 16×16 四灰阶图标预览，保留 9288 系统边框。
- 一键原生转换，显示真实阶段、耗时与日志，支持取消。
- 名称写入 KF2 和应用标题；默认输出文件名跟随名称。
- 编译成功、链接完整及体积检查通过后才替换旧 EXE。
- 包含原生游戏代码、压缩资源和共享运行库；真机运行不需要 GAM、BIN 或 GNA 文件。
- 分发包自带 Python/Tk/Pillow 与 PC 启动状态生成工具，不依赖开发者的 Python 安装路径。

## 快速开始（Windows）

1. 从 [Releases](https://github.com/HelloClyde/a-series-9288-translator/releases) 下载 Windows ZIP，
   **完整解压**，运行 `A9288-Converter.exe`。尚未打发布 tag 时，可从成功的 Actions 下载构建产物。
2. 在“编译环境”中配置：9288 SDK、修正过 9288 ABI 的 S1C33 LLVM 工具链、A 系列 `8.BIN` 和 `E.BIN`。
3. 选择自己有权使用的 GAM，设置名称、图标和输出位置，点击转换。
4. 将生成的 EXE 复制到真机 `A:\系统\程序\`，在“娱乐”分类启动。

SDK 和固件不随仓库/ZIP 分发。仅支持 **9288 SDK**，不能用 9588 SDK 替代。
工具链不是普通 LLVM；构建方法见 [工具链说明](toolchain/README.md)。

名称最多 15 个 GBK 字节（通常 7 个汉字），不支持 emoji。9288 桌面标签采用 EXE
文件名；另行修改输出文件名也会改变桌面标签。每次生成同名 `.elf`、`.map` 和
`.report.json`，真机只需 EXE。工作目录默认 `%LOCALAPPDATA%\A9288\work`。

## 开发与命令行

需要 Python 3.11+；源码运行还需要 Tkinter、PC GCC。Windows 分发包自带预编译 PC helper。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m a9288 gui

.venv\Scripts\python -m a9288 convert "游戏.gam" --app-name "游戏名称" `
  --sdk "你的9288SDK目录" --toolchain "你的S1C33工具链目录" `
  --rom8 "你的固件目录\8.BIN" --rome "你的固件目录\E.BIN" --output "游戏名称.exe"
```

可使用 `A9288_SDK`、`A9288_TOOLCHAIN`、`A9288_ROM8`、`A9288_ROME` 设置默认值。
`A9288_WORKSPACE` 可覆盖工作目录。不会联网上传游戏、图标或转换产物。

## 项目结构

```text
src/a9288/
  gui.py, cli.py       界面与公共转换入口
  app_options.py      GAM 校验、名称和图标策略
  paths.py            安装路径、工作区、子进程协议
  compiler/
    frontend.py       函数、调用关系和控制流恢复
    cfg.py, isa.py    6502 解码与控制流基础设施
    semantics.py     C6502 编译器语义模板
    functions.py     函数分组与跨 bank 目标恢复
    backend.py       S1C33 原生代码生成
    build.py, kf2.py 原生运行库链接与 KF2 封装
    boot.py          PC 离线启动状态准备
    compression.py   资源压缩
  data/
    runtime/         真机原生运行库、链接脚本、9288 兼容头
    boot_reference/  仅 PC 使用的参考核心，绝不链接进真机 EXE
    icons/           默认图标
    c6502_symbols.json  开发包中的函数名/地址事实表
tests/               无游戏单元测试、可选固件等价测试
scripts/             打包、分发校验与依赖构建
packaging/           Windows 冻结配置和启动入口
toolchain/           固定版本与 9288 ABI 补丁
docs/                架构、兼容性、发布和维护说明
.github/workflows/   CI、Windows 构建、tag 发布
```

## CI 与发布

- push 到 `main`、PR 或手动触发 **Build**：测试、代码检查、构建 Windows 分发包和 SHA-256 校验文件。
- 推送 `v*` tag：同一套检查与构建通过后自动创建 GitHub Release 并上传 ZIP、校验文件。
- release 使用严格的 tag/版本一致性检查；普通 PR 没有发布权限。
- LLVM 工具链使用独立的手动构建 workflow，固定源代码提交并应用仓库中的 ABI 补丁。

本地构建：`python scripts/build_windows.py`。发布约定详见 [发布流程](docs/releasing.md)。

## 兼容性与原理

译出的控制流使用 S1C33 原生分支和 call/ret；不生成运行时 opcode 解释分派器，也不
在未知调用处静默退回解释器。图片、文字、输入、计时等由共享原生运行库适配。
PC 启动准备阶段仍使用参考核心生成初始 RAM/寄存器状态，它不参与真机运行。

已有《伏魔记》和《魔塔之怀旧终曲》的局部功能验证。不同游戏、SDK 和固件版本可能
存在不兼容；请参阅 [架构与限制](docs/architecture.md)。未知适配入口、未恢复的调用、
超过当前 1 MiB 限制的 KF2 会使构建失败，不代表所有其他输入均已正确翻译。

## 开源与来源

源自 [BBK9288-gam4980](https://github.com/HelloClyde/BBK9288-gam4980) 的原生编译器工作，
整理为独立项目。代码使用 GPL-3.0；具体来源、固件/SDK 与商标边界见
[第三方说明](THIRD_PARTY_NOTICES.md)。仓库、CI 和 release 均不携带商业 GAM 或编译后的游戏。

反馈问题请附转换报告和日志，默认不要上传游戏、存档、固件或个人路径。

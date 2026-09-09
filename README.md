# GAMForge

**经典游戏，原生新生。**

GAMForge · GAM 原生重编译器

将 BBK A 系列 GAM 游戏离线重编译为 BBK 9288 原生程序。

Recompile BBK A-series GAM games into native BBK 9288 applications.

[![CI](https://github.com/HelloClyde/gamforge/actions/workflows/build.yml/badge.svg)](https://github.com/HelloClyde/gamforge/actions/workflows/build.yml)
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
- 默认单 EXE 内置压缩资源；可选“EXE＋外置资源文件”，用于资源较大的游戏。
- 两种模式均包含原生游戏代码和共享运行库，真机不需要原 GAM、BIN 或 GNA 文件。
- 分发包自带 Python/Tk/Pillow 与 PC 启动状态生成工具，不依赖开发者的 Python 安装路径。

## 快速开始（Windows）

1. 从 [Releases](https://github.com/HelloClyde/gamforge/releases) 下载 Windows ZIP，
   优先选择名称含 **`full-windows-x64.zip` 的全套版**，完整解压后运行 `GAMForge.exe`。
   当前版本为 [v1.1.2](https://github.com/HelloClyde/gamforge/releases/tag/v1.1.2)。
2. 全套版已配好所需 SDK、工具链和固件，无需安装 Python、编译器或手动填写路径。
   不含 `full` 的轻量版仍需在“编译环境”中自行配置这些依赖。
3. 选择自己有权使用的 GAM，设置名称、图标和输出位置，点击转换。
4. 将生成的 EXE 复制到真机 `A:\系统\程序\`，在“娱乐”分类启动。

全套版包含经维护者确认获授权分发的所需 SDK 头文件和固件；源码仓库和轻量版不含它们。
请保留包内 `dependencies`、`_internal` 目录，不要只复制单个 EXE。支持 Windows 10/11 x64。
仅支持 **9288 SDK**，不能用 9588 SDK 替代。
工具链不是普通 LLVM；构建方法见 [工具链说明](toolchain/README.md)。

名称最多 15 个 GBK 字节（通常 7 个汉字），不支持 emoji。9288 桌面标签采用 EXE
文件名；另行修改输出文件名也会改变桌面标签。每次生成同名 `.elf`、`.map` 和
`.report.json`。单文件模式真机只需 EXE；外置模式还需配套 RES。
工作目录默认 `%LOCALAPPDATA%\A9288\work`。

### EXE＋外置资源文件（v1.1.0 新增）

在转换界面勾选 **EXE＋外置资源文件**，或在下方命令末尾添加
`--external-resources`。成功后输出 EXE 和内容标识命名的 `Rxxxxxxx.RES`。
将 EXE 复制到真机 **`A:\系统\程序\`**，RES 复制到 **`A:\系统\数据\`**。
不要重命名 RES，也不要混用其他转换的资源。

外置模式仍是 PC 离线编译的原生程序，不会在真机解释 GAM 指令。
资源采用 4 KiB 分页、128 KiB 固定缓存，不再启动时分配完整 GAM。
游戏对资源地址的写入保存在独立的会话内存（上限 256 KiB），不改写 RES；
缺失、版本不匹配、损坏、读取失败或内存不足会报错退出。
正常游戏存档仍由原有存档接口处理。

此选项解决资源导致的 EXE 体积和整份资源内存问题；原生代码本身仍受
1 MiB KF2 限制，不能保证任意游戏兼容。缓存未命中需要读盘，实际速度需真机验证。
RES 包含游戏数据，和游戏 EXE 一样不应提交到本项目仓库或翻译器分发包。

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

已有《伏魔记》《魔塔之怀旧终曲》和《三国霸业》的局部功能验证与真机反馈。
1.0 包含直接 framebuffer 输出、行批量绘图、私有键盘轮询、退出恢复及 Timer 时钟回退防护；
本轮 CLOCK-GUARD-1 已通过模拟器故障注入，长期真机稳定性仍需持续验证。
不同游戏、SDK 和固件版本可能
存在不兼容；请参阅 [架构与限制](docs/architecture.md)。未知适配入口、未恢复的调用、
超过当前 1 MiB 限制的 KF2 会使构建失败，不代表所有其他输入均已正确翻译。

## 开源与来源

源自 [BBK9288-gam4980](https://github.com/HelloClyde/BBK9288-gam4980) 的原生编译器工作，
整理为独立项目。代码使用 GPL-3.0；具体来源、固件/SDK 与商标边界见
[第三方说明](THIRD_PARTY_NOTICES.md)。仓库、CI 和 release 均不携带商业 GAM 或编译后的游戏。

感谢以下作者提供的基础工作：

- **钳工**：9288 SDK。
- **无云、iyzsong**：4980 模拟器。

反馈问题请附转换报告和日志，默认不要上传游戏、存档、固件或个人路径。

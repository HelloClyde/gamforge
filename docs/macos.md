# macOS 使用与打包

新增 Mac 宿主支持，输出仍是 BBK 9288 / 9288T / 9288S / 听说王600 的原生 EXE，
不是把游戏转换为 Mac 游戏。

## 当前状态

已加入 Apple Silicon `arm64` 与 Intel `x86_64` 的源码适配、`.app` / CLI 打包入口和
双架构 CI。**当前 v1.4.0 Release 仍仅有 Windows 资产；本次 Mac 支持尚未经过 Mac
runner 实际执行，也未发布 Mac 下载包。** Windows 单元测试不能代替 Mac 原生构建和 GUI 验证。

构建目标最低系统为 macOS 11；打包器检查每个 Mach-O 的实际最低版本，若依赖要求
更高版本则拒绝生成误标的包。CI 计划运行于 macOS 15，不能据此宣称所有 macOS 11+
机器、游戏或真机流程都已验证。后续发布以实际资产和 CI 记录为准。

## 使用分发包

发布 Mac 资产后，按“关于本机”的芯片选择 `macos-arm64.zip`（Apple Silicon）或
`macos-x86_64.zip`（Intel）。不要混用架构，不要求 Rosetta，也不能运行 Windows ZIP
中的工具链。完整解压后打开 `GAMForge.app`，或在终端运行 `./GAMForge-CLI --help`。

轻量包自带 Python、Tk、Pillow 和本机启动 helper，但转换前还需配置：

- 目标机型的 SDK 头文件：9288、9288T、9288S 分别使用对应 SDK，听说王600 共用 S SDK。
- A 系列 `8.BIN`、`E.BIN`：使用有权使用的固件，各 2 MiB。
- 同架构 **Mac 原生 S1C33 LLVM**：包括 `clang`、`ld.lld`、`llvm-objcopy`、`llvm-readelf`，
  必须包含本仓库固定版本的 S1C33 后端与 9288 GNU33 ABI 补丁。

Apple 自带 Clang 只用于在 Mac 构建 PC helper，**不能生成 S1C33 游戏程序**。
普通 Homebrew LLVM 同样不能替代定制工具链。Windows `.exe` 不会被当作 Mac 可执行文件。

授权全套版采用 `full-macos-<架构>.zip` 命名，只有此包才包含转换所需依赖；
“有全套打包脚本”不代表完整包已经可下载。轻量与全套均不含 GAM、游戏 EXE 或 RES。

包布局：

```text
GAMForge/
  GAMForge.app/
    Contents/MacOS/GAMForge
    Contents/Resources/dependencies/   # 仅授权全套版
  GAMForge-CLI                        # 旁置命令行启动器
  MACOS-BUNDLE.json
  MANIFEST.sha256.json
  BUNDLE-FILES.json
  licenses/
```

可将 `.app` 移到“应用程序”；全套依赖在 `.app` 内会一起移动。旁置 CLI 脚本需要与
`.app` 保持同目录，也可直接调用 `/Applications/GAMForge.app/Contents/MacOS/GAMForge`。
不要修改 `.app` 内部内容，否则会破坏签名与校验。配置、日志和临时工作位于
`~/Library/Application Support/GAMForge/`；`A9288_USER_DATA`、`A9288_WORKSPACE`
可显式覆盖用户数据和工作目录。

### 首次打开与安全提示

当前构建只做 ad-hoc 签名，**不具有 Developer ID，也未经 Apple 公证**。先确认下载来自
本项目官方 Release，并在下载目录校验 `shasum -a 256 --check <文件名>.zip.sha256`。

如果 macOS 因未识别开发者阻止启动，在确认来源和校验结果后，按系统提示进入
“系统设置 → 隐私与安全性”，仅允许这个应用打开。若系统报告恶意软件或文件损坏，
应停止并重新核验/反馈；不要一律绕过。不要全局关闭 Gatekeeper、SIP 或执行批量移除
隔离属性的命令。说明依据见 [Apple：安全打开 Mac 上的 App](https://support.apple.com/en-us/102445)。

## 从源码运行

准备 Python 3.11+（建议与 CI 一致的 3.12）、Tkinter 和 Xcode Command Line Tools。
可使用 python.org 的 macOS Python；其安装包自带匹配的 Tcl/Tk，不使用系统旧 Tk。
见 [Python 官方 Tcl/Tk 说明](https://www.python.org/download/mac/tcltk/)。

```sh
xcode-select --install                 # 已安装 Command Line Tools 时跳过
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m tkinter                     # 能打开测试窗口后关闭它
python -m a9288 --self-test
python -m a9288 gui
```

转换示例（示例路径需替换为自己的依赖和游戏）：

```sh
python -m a9288 convert "$HOME/Games/游戏.gam" \
  --target 9288t --app-name "游戏名称" \
  --sdk "$HOME/BBK/sdk9288t" \
  --toolchain "$HOME/BBK/s1c33-9288-toolchain-macos-arm64" \
  --rom8 "$HOME/BBK/roms/8.BIN" --rome "$HOME/BBK/roms/E.BIN" \
  --output "$HOME/Desktop/游戏名称.exe"
```

Intel Mac 改用 `macos-x86_64` 工具链。SDK、固件路径也可在 GUI“编译环境”中设置，
或使用与 Windows 相同的 `A9288_SDK` / `A9288T_SDK` / `A9288S_SDK`、
`ATSW600_SDK`、`A9288_TOOLCHAIN`、`A9288_ROM8`、`A9288_ROME` 环境变量。

默认内置资源只需将生成的 EXE 安装到机器 `A:\系统\程序\`。
添加 `--external-resources` 后，配套 RES 还需复制到 `A:\系统\数据\`，不能重命名。
Mac 宿主不改变输出格式、游戏存档路径、默认缩放或游戏兼容性边界。

## 维护者打包

### 原生工具链

重型 LLVM 构建与普通应用 CI 分开，避免每次 UI 修改都重编 LLVM。可手动运行
**Build S1C33 toolchain**，或在对应架构 Mac 上安装 CMake、Ninja、Git 后执行：

```sh
python scripts/build_toolchain.py --jobs 2 --reuse \
  --expect-host macos-arm64 --deployment-target 11.0
```

Intel 使用 `--expect-host macos-x86_64`。源代码、补丁和 ABI 固定方式见
[工具链说明](../toolchain/README.md)。产物为
`dist/s1c33-9288-toolchain-macos-<架构>.zip`，工具没有 `.exe` 后缀。
脚本实际执行编译、链接、ELF 检查和提取探针；不只检查版本字符串。

```sh
python scripts/build_toolchain.py --expect-host macos-arm64 \
  --verify-only /path/to/s1c33-9288-toolchain-macos-arm64
```

### 轻量应用

必须在匹配 CPU 架构的 Mac/Python 上打包，不支持从 Windows 假造 `.app`：

```sh
python -m pytest
python scripts/build_macos.py --architecture arm64 --minimum-macos 11.0 \
  --tk-notices-manifest build/license-input/TCLTK-NOTICES.json
```

打包前需准备当前 Python 实际加载的 Tcl/Tk 许可，不从其他 Python 安装中随意取一份。
CI 的 [Collect notices 步骤](../.github/workflows/build.yml)读取 `info patchlevel`（Tcl）与
`package require Tk`（Tk）完整版本，分别下载官方 `tcltk/tcl`、`tcltk/tk` 仓库
`core-X-Y-Z` tag 下的 `license.terms`，然后生成上述 manifest；本地构建可执行同一步骤。
该下载仅获取许可文本，不下载或执行 Tcl/Tk 代码。若版本没有对应 tag 或许可缺失，构建失败，
不能换用“差不多”的版本。离线维护者可以预先保存同一版本的许可文本和 manifest。

Manifest 包含 `schema: 1` 以及 `tcl`、`tk` 两项，每项记录实际 `version`、官方
`source_url`、相对 manifest 目录的 `path` 和文件 `sha256`。打包器重新核对版本、来源和
哈希，把完整许可及来源记录放入发布包；许可文件是否随 Python 安装不再决定构建成败。

输出 `dist/gamforge-<版本>-macos-arm64.zip` 和 `.zip.sha256`；Intel 改为 `x86_64`。
打包器编译本机 helper、冻结 GUI/CLI、执行隔离环境下的 frozen 自检与 worker，核验
Mach-O 架构、最低系统和 ad-hoc 签名。ZIP 保留 `.app` 的框架符号链接和执行权限。
解压应使用 Finder / Archive Utility 或 `ditto -x -k`，不要用丢弃这些属性的解压工具。

### 授权全套版

维护者需持有 SDK/固件分发授权，并提供 **本机架构工具链**。将上述已验证轻量 ZIP
解压到独立目录，然后执行：

```sh
ditto -x -k dist/gamforge-<版本>-macos-arm64.zip build/mac-light
python scripts/build_full_bundle.py \
  --platform macos --architecture arm64 \
  --portable-dir build/mac-light/GAMForge \
  --sdk /path/to/sdk9288 --sdk9288t /path/to/sdk9288t \
  --sdk9288s /path/to/sdk9288s \
  --toolchain /path/to/s1c33-9288-toolchain-macos-arm64 \
  --rom8 /path/to/8.BIN --rome /path/to/E.BIN \
  --authorized-redistribution
```

`<版本>` 是占位符，终端执行前必须替换。Mac 不传 `--vc-runtime`；不能将 Windows CRT
或 `.exe` 放入 Mac 包。全套打包将依赖放进 `Contents/Resources/dependencies`，保留
来源、许可与逐文件哈希，重新签名，并检查工具链不依赖 Homebrew 或开发者的私有绝对路径。

发布前还须在解压后的全套包中清除开发者依赖环境变量，使用包内 CLI 实际转换自备游戏：
覆盖四个目标、默认锐利 9288T、外置 RES、中文路径和 `.app` 移动后的启动。
把转换产物留在包外，不能加入 Release ZIP；验证结果明确记录宿主系统、架构及未覆盖范围。

## CI 与验证边界

主 Build workflow 保留 Windows x64，并增加两个原生 Mac job：

| 架构 | GitHub runner | setup-python 架构 |
| --- | --- | --- |
| Apple Silicon | `macos-15` | `arm64` |
| Intel | `macos-15-intel` | `x64` |

标签与架构来自 [GitHub 官方 runner 文档](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)，
不使用会随时间改变平台含义的 `macos-latest`。Python 3.12 的安装来源依据
[setup-python 官方构建实现](https://github.com/actions/python-versions/blob/main/builders/macos-python-builder.psm1)，
CI 仍会实际创建 Tk 窗口以检查配置，不把“能 import tkinter”等同 GUI 工作正常。
许可来源根据实际加载的 Tcl、Tk 各自版本确定并记录，不以 Python 版本推测，
也不会混用另一环境的 Tcl/Tk 声明。

Mac CI 执行测试、本机 helper、冻结 worker、自检，以及解压 ZIP 后的实际 GUI 窗口和图标预览
烟雾测试；后者不运行游戏、不转换用户数据。所有三平台成功后，tag 发布阶段才收集轻量 ZIP
及 SHA-256；SDK/固件和全套包不会自动从维护者电脑上传。

CI 不提供版权 GAM，因此其通过不等于实际游戏全流程、Mac 所有版本或 BBK 真机验证。
当前工作仅接通这些检查，尚无本轮 Mac CI 成功记录；发布时必须补齐实际运行结果。

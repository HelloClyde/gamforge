# 构建与发布

## 默认发布策略

正式下载默认全部为 Full，不再让用户自行安装转换依赖：

- Windows x64：`gamforge-<版本>-full-windows-x64.zip`。
- Apple Silicon Mac：`gamforge-<版本>-full-macos-arm64.zip`。
- Intel Mac：`gamforge-<版本>-full-macos-x86_64.zip`。

每包包含 Python/Tk/Pillow、PC 启动 helper、四机型所需 SDK 头文件、A 系列固件和
对应宿主原生 S1C33 工具链。Windows 还包含 app-local VC 运行库；Mac 不放 Windows
程序或 CRT，采用 ad-hoc 签名但未经 Apple 公证。所有包都不含游戏、游戏 EXE、RES 或存档。

这是后续发布流程要求，不修改已发布 tag：v1.5.0 首次发布为三平台轻量包，v1.4.0
有 Windows Full。不能把历史无依赖附件改名为 Full；实际是否可下载以 Releases 附件为准。

## 自动构建

`Build` 在 `main` push、pull request、`v*` tag 和 `workflow_dispatch` 时运行。
所有平台先执行代码检查、测试、本机 helper 和 GUI/CLI 轻量中间产物构建及冻结自检。
PR 只上传开发用轻量测试产物，不获取发布写权限。

main、tag 与常规手动构建继续自动准备 Full：

1. 从固定来源、按固定 SHA-256 提取维护者已确认获授权的 SDK/固件；Windows CRT 仅取
   原生 runner 的 Visual Studio `VC/Redist/MSVC/<版本>/x64/Microsoft.VC*.CRT` 可分发目录。
2. 按宿主架构构建或复用 S1C33 工具链；缓存身份包含固定 LLVM 提交、ABI 补丁和构建脚本，
   复用前仍执行工具链验证，不用 Windows 程序冒充 Mac 工具。
3. 组装 Full 包，保留许可证、`FULL-BUNDLE.json`、依赖清单和文件哈希。
4. 解压到独立位置，清除开发者 SDK/工具链/固件环境覆盖，用包内冻结 CLI 转换合成 GAM，
   覆盖 9288、9288T 默认锐利、9288S、听说王600；再移动到中文空格路径验证外置 RES。
5. 上传每个平台的 Full ZIP、SHA-256 和独立验证记录。合成输入和转换产物不进入分发包。

合成输入由仓库脚本生成，不下载商业游戏。固件等价测试在 `A9288_ROME` 未配置时明确跳过；
普通单元测试无需私人文件。Full 的隔离转换验证不得因缺少依赖而跳过，不能把应用自检
通过当作完整转换链通过。CI 通过也不等于实际游戏全流程或 BBK 真机验证。

两种 Mac 的原生构建、签名和安全提示见 [macOS 使用与打包](macos.md)。独立工具链 workflow
和指定 `app_run_id` / `toolchain_run_id` 的跨工作流 Mac Full 验证仍保留，后者只产生 Actions
artifact，不发布 Release；二者均不是默认发布需要维护者另行手工完成的步骤。

## 维护者本地组装 Full

先构建同版本轻量 Windows 包，再由获 SDK/固件分发授权的维护者执行：

```powershell
python scripts/build_full_bundle.py --sdk "9288 SDK路径" --sdk9288t "9288T SDK路径" `
  --sdk9288s "9288S SDK路径" `
  --toolchain "工具链路径" `
  --rom8 "固件目录/8.BIN" --rome "固件目录/E.BIN" `
  --vc-runtime "Visual Studio/VC/Redist/MSVC/版本/x64/Microsoft.VC142.CRT" `
  --authorized-redistribution
```

工具只打包所需 SDK 头文件、四个工具链程序与 app-local CRT、固件，不打包游戏。
生成 `full-windows-x64.zip` 和校验文件。解压到新的目录，清除 A9288/Python 环境覆盖、
使用独立 LOCALAPPDATA 和仅 System32 的 PATH，以包内 CLI 不带 SDK/工具链/固件参数实际
转换用户有权使用的测试游戏。游戏产物只保留本地，验证后才将全套 ZIP 和校验上传对应 Release。
此步骤也由默认 Full CI 自动完成；本地手动组装用于维护验证，不是最终用户的安装流程。
不得把 SDK/固件提交源码来绕过授权来源与校验。

## 发布版本

1. 更新 `src/a9288/__init__.py` 和 `pyproject.toml` 的版本，并更新 CHANGELOG。
2. 合并至 main，等待 Build 成功。
3. 在准备发布的提交上创建并推送 tag：

```shell
git tag -a v1.0.0 -m "GAMForge · GAM 原生重编译器 1.0.0"
git push origin v1.0.0
```

tag 版本必须与两处元数据完全一致。tag build 再次测试并构建，**Windows 与两种 Mac 的
Full 组装、隔离转换全部成功**后 release job 才能继续。发布前严格检查三个预期 Full ZIP、
对应 SHA-256 与验证记录的完整性和版本；缺包、检查失败或混入轻量 ZIP 均阻止发布。
通过后以 `contents: write` 权限创建草稿、上传本次 Full 产物和验证记录，再公开 release。
普通测试/构建 job 只有 `contents: read`。没有设置 `pull_request_target`，也不执行
外部 PR 提供的发布步骤。

已发布 tag 不覆写，已存在 release 不自动 `--clobber`。若上传中断留下 draft，
由维护者检查并处理后重跑。不要为了重试而强推已发布 tag。

不需要个人 access token：发布使用该 workflow 的 `GITHUB_TOKEN`。
仓库或组织如限制 Actions 的写权限，需要管理员允许 release job 的声明权限。

## Full 发布检查

- 三个平台必须同时具备同版本 Full ZIP、校验文件和独立验证记录；失败不能退回轻量包。
- Full 包不依赖开发者的 Python、SDK、ROM、工具链或机器绝对路径；默认路径应自动指向包内依赖。
- 核对 `FULL-BUNDLE.json` 的目标列表、文件清单、依赖来源及哈希，SDK 与输出机型分别匹配。
- 四目标合成转换、外置 RES、中文路径和应用搬迁检查均成功；Mac 保留执行权限、框架链接和签名。
- 保留所有第三方许可证；Windows CRT 来源必须是合法可分发的 Release 目录，不从系统目录收集。
- 不携带商业 GAM、合成验证输入、游戏 EXE、RES、存档、用户日志、配置或凭据。

## 轻量中间产物 / PR 测试包检查

- ZIP 内 GUI 和 CLI 必须能在没有本项目 Python 环境的情况下运行。
- `GAMForge-CLI.exe --self-test` 必须返回 PASS，且 `boot_helper=true`。
- `--worker compiler.backend --help` 必须成功，验证冻结进程协议。
- 不得携带 GAM、存档、SDK、固件、用户日志或游戏 EXE。
- `licenses/` 保留构建环境的 CPython、Pillow、PyInstaller、Tcl/Tk 许可与版本记录。
- `toolchain/` 随包提供构建说明和 ABI 补丁，但不包含 LLVM 二进制或 SDK。
- 轻量中间产物与历史轻量包若单独使用，SDK、ROM 和 LLVM 工具链需自行配置，不能标为 Full。

以上依赖排除规则适用于轻量包；获授权的全套包按前述流程附带对应 SDK 头文件、
固件与工具链，并验证 `FULL-BUNDLE.json` 的目标列表、文件清单及隔离环境转换。
两种包都不得包含游戏、游戏 EXE、RES 或存档。新的正式 Release 只发布 Full，不同时发布
容易被误认为解压即用的轻量 ZIP。

从 v1.3.0 起，S / 听说王600 用 `--sdk9288s` 附带共用的 `Down_Include`。
`FULL-BUNDLE.json` 分别列出 `9288s`、`tsw600`；隔离环境分别实际转换，
600 使用独立 D300 标记和“游戏”分类。S 验证不能标成 600 真机验证。

在 Windows 本地运行 `python scripts/build_windows.py` 可执行同一打包/自检流程。
生成文件在 `dist/`，不加入 Git。轻量应用构建不是 Full 组装的替代步骤；默认 CI 利用
经过验证的工具链缓存，避免每次应用提交都重新编译庞大的 LLVM。

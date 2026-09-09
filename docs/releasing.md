# 构建与发布

## 全套离线版

先构建同版本轻量 Windows 包，再由获 SDK/固件分发授权的维护者执行：

```powershell
python scripts/build_full_bundle.py --sdk "9288 SDK路径" --toolchain "工具链路径" `
  --rom8 "固件目录/8.BIN" --rome "固件目录/E.BIN" `
  --vc-runtime "Visual Studio/VC/Redist/MSVC/版本/x64/Microsoft.VC142.CRT" `
  --authorized-redistribution
```

工具只打包所需 SDK 头文件、四个工具链程序与 app-local CRT、固件，不打包游戏。
生成 `full-windows-x64.zip` 和校验文件。解压到新的目录，清除 A9288/Python 环境覆盖、
使用独立 LOCALAPPDATA 和仅 System32 的 PATH，以包内 CLI 不带 SDK/工具链/固件参数实际
转换用户有权使用的测试游戏。游戏产物只保留本地，验证后才将全套 ZIP 和校验上传对应 Release。
普通 CI 无第三方依赖，继续构建轻量版；不得把 SDK/固件提交源码来绕过此流程。

## 普通构建

`Build` 在 `main` push、pull request 和 `workflow_dispatch` 时运行。
它执行代码检查、测试，在 Windows 构建 PC helper 和 GUI/CLI 分发包，运行冻结包自检，
然后上传 ZIP、SHA-256 和打包清单。公开 CI 无需 SDK、ROM、GAM 或仓库 secret。

固件等价测试在 `A9288_ROME` 未配置时明确跳过；其余单元测试不需要私人文件。
CI 自检使用程序生成的微型指令样本，不下载或编译商业游戏。

## 发布版本

1. 更新 `src/a9288/__init__.py` 和 `pyproject.toml` 的版本，并更新 CHANGELOG。
2. 合并至 main，等待 Build 成功。
3. 在准备发布的提交上创建并推送 tag：

```shell
git tag -a v1.0.0 -m "A 系列 9288 翻译器 1.0.0"
git push origin v1.0.0
```

tag 版本必须与两处元数据完全一致。tag build 再次测试并构建，成功后 release job
以 `contents: write` 权限创建草稿、上传本次 artifact，再公开 release。
普通测试/构建 job 只有 `contents: read`。没有设置 `pull_request_target`，也不执行
外部 PR 提供的发布步骤。

已发布 tag 不覆写，已存在 release 不自动 `--clobber`。若上传中断留下 draft，
由维护者检查并处理后重跑。不要为了重试而强推已发布 tag。

不需要个人 access token：发布使用该 workflow 的 `GITHUB_TOKEN`。
仓库或组织如限制 Actions 的写权限，需要管理员允许 release job 的声明权限。

## 分发检查

- ZIP 内 GUI 和 CLI 必须能在没有本项目 Python 环境的情况下运行。
- `A9288-CLI.exe --self-test` 必须返回 PASS，且 `boot_helper=true`。
- `--worker compiler.backend --help` 必须成功，验证冻结进程协议。
- 不得携带 GAM、存档、SDK、固件、用户日志或游戏 EXE。
- `licenses/` 保留构建环境的 CPython、Pillow、PyInstaller、Tcl/Tk 许可与版本记录。
- `toolchain/` 随包提供构建说明和 ABI 补丁，但不包含 LLVM 二进制或 SDK。
- 用户的 9288 SDK、ROM 和 LLVM 工具链需自行配置；当前没有把这些外部依赖称为“全内置”。

在 Windows 本地运行 `python scripts/build_windows.py` 可执行同一打包/自检流程。
生成文件在 `dist/`，不加入 Git。可选工具链 workflow 只需手动触发，不会在每次应用
提交时重新编译庞大的 LLVM。

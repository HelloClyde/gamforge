# 第三方来源与分发边界

## 项目代码

本项目从 HelloClyde/BBK9288-gam4980 的 PC 原生编译链拆分，保留原有 GPL v3
许可文件。来源：<https://github.com/HelloClyde/BBK9288-gam4980>。
参考核心的移植来源还包括 <https://github.com/HelloClyde/BBK9588-gam4980>。
4980 模拟器来自 **无云、iyzsong**，感谢两位作者的基础工作。
原生运行库、编译器、测试和本项目新增界面遵循仓库 LICENSE；保留已有作者声明。

`src/a9288/data/boot_reference` 是 PC 工具的参考实现，不是生成 EXE 的运行时解释器。
发布包包含其源文件及预编译 helper；源码仓库/同版本 tag 提供对应源代码。

## LLVM 工具链

工具链来自 <https://github.com/autch/llvm-s1c33>，固定提交见 `toolchain/manifest.json`。
LLVM 本身使用 Apache-2.0 WITH LLVM-exception；本项目提供 9288 GNU33 ABI 修正补丁。
工具链单独构建和分发时保留上游 `llvm/LICENSE.TXT`、源码提交和补丁；并不将 LLVM
改成 GPL 许可。轻量 ZIP 不含工具链；全套 ZIP 包含所需工具、LLVM 许可、补丁和来源记录。

## Python、GUI 与打包

Windows 分发包由 PyInstaller 构建，包含 CPython、Tcl/Tk、Pillow 等组件。
各组件保留其独立许可；PyInstaller 的 bootloader exception 允许构建应用分发包。
发布脚本从实际构建环境收集 CPython、Pillow、PyInstaller 的许可证，以及冻结包中的
Tcl/Tk `license.terms`，放入包内 `licenses/`，并记录构建组件版本。缺失许可证时构建失败。
维护者还应审查每次构建的依赖清单，具体直接依赖在 `pyproject.toml` 和 `requirements-dev.txt`。

## SDK、固件、游戏与资源

9288 SDK 来自 **钳工**，感谢其提供的开发基础。

全套包中的工具链使用 Microsoft Visual C++ 运行库，以 app-local 方式保留原始 x64 CRT DLL。
文件取自已安装 Visual Studio Build Tools 的 `VC/Redist/MSVC/.../x64/Microsoft.VC142.CRT`，
不从 Windows 系统目录抓取，不包含 debug_nonredist。Microsoft 组件不属于本项目 GPL：
https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files
https://learn.microsoft.com/en-us/visualstudio/releases/2019/redistribution

- 9288 SDK 和 A 系列 `8.BIN` / `E.BIN` 不进入源码或普通 CI 轻量包。
  维护者已确认获授权分发所提供的 SDK（钳工 SDK）和配套固件；全套包仅包含所需 SDK 头文件与固件，
  不包含商业 GAM、游戏 EXE、RES 或存档。该分发授权不等于将第三方组件改为 GPL。
  全套包的 `FULL-BUNDLE.json` 记录实际依赖哈希和工具链版本。
- `c6502_symbols.json` 仅记录 C6502 开发包 `test.map` 中函数名/地址事实，未包含
  完整开发包、编译器二进制或 SDK 实现。
- `runtime/c6502_native_query_assets.h` 中的小型对话框位图常量源于兼容性逆向，
  不应解释为对原固件美术资产的所有权声明；若权利方提出异议，请联系维护者处理。
- 默认图标沿用原项目生成的四灰阶设备图案和 9288 风格边框；设备名称、商标属于相应权利人，
  本项目不是步步高官方产品。
- 原生转换后的 EXE 包含用户游戏资源；项目不会将其自动公开、纳入源码或上传 release。

 版权、商标或许可问题请在仓库联系维护者，并避免在公开 issue 粘贴完整游戏/固件。

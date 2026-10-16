# 参与开发

先安装 `requirements-dev.txt`，执行：

```shell
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pytest
python -m a9288 --self-test
```

新增翻译模板时，用合成字节序列覆盖正确路径、边界和拒绝路径；不要提交商业 GAM。
修改函数参数、计时、绘图或银行语义时，优先添加可选 ROM 等价测试，不能只凭截图
断言正确。说明测试场景与尚未验证的范围。

工作原则：编译器、界面和真机运行库分层；未知调用明确失败；不在编译失败时覆盖旧输出；
不加入运行时解释器回退；不硬编码个人目录；不通过更改模拟器来掩盖真机错误。

保留第三方作者/许可声明。修改 PC 参考实现时注明它不属于真机运行代码。

## macOS 宿主

Mac 源码运行、原生工具链与 `.app` 打包见 [macOS 文档](docs/macos.md)。Apple Silicon
和 Intel 需分别在匹配架构的 Mac/Python 上构建；不要把 Windows `.exe` 改名或复制成
Mac 工具，不将 Rosetta/Wine 当作原生支持。

修改宿主路径、子进程、冻结资源或依赖发现时，覆盖 `.app/Contents` 布局、中文/空格路径、
可移动完整包与只读应用目录。配置和临时文件写用户目录，不能写入签名应用内部。
Mac ZIP 必须保留执行位和相对符号链接，重新解压后验证签名、CLI 和实际 GUI 烟雾测试。
`python -m a9288 --gui-smoke-test` 仅用于短暂创建和销毁界面，不应转换游戏或保存用户设置。

主 CI 测试两个 Mac 架构和 Windows；重型 S1C33 LLVM 采用独立 workflow，仍需本机
编译/链接/ELF 探针。不要因 Windows 上的模拟路径单测通过就记录为 Mac 构建或 GUI 已验证。
全套包仅在有 SDK/固件授权时打包，发布前使用隔离配置实际转换，且不得携带测试游戏。

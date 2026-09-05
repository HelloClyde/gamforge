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

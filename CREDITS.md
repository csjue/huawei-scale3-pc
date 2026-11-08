# 致谢与来源 / Credits

这个项目不是从零逆向的，它站在三个已有开源/公开工作的肩膀上。

## 上游项目

| 项目 | 作者 | 许可证 | 本项目用到什么 |
| --- | --- | --- | --- |
| [Peter-Maguire/hacs-huawei-scale](https://github.com/Peter-Maguire/hacs-huawei-scale) | Peter Maguire | GPL-3.0 | `custom_components/huawei_scale3/` 下全部协议源码（protocol / session / const / body_composition / models）与 `tests/` 下的模拟秤和测试 |
| [oliexdev/openScale](https://github.com/oliexdev/openScale) | openScale contributors | GPL-3.0 | 华为 Hagrid WSP 驱动 `HuaweiHagridWspLib.kt`、`HuaweiScale3BodyComposition.kt` 的原始实现与参考向量；[issue #763](https://github.com/oliexdev/openScale/issues/763) |
| [petermaguire.xyz 协议逆向文章](https://petermaguire.xyz/posts/huawei-scale-ble-protocol) | Peter Maguire | — | 握手流程与密钥派生机制的公开梳理（本项目不复刻、不分发这些常量） |

上游 HACS 集成面向 Home Assistant / ESPHome 蓝牙代理；本项目把它剥离成**纯 `bleak` 的桌面命令行工具**，因此也遵守 GPL-3.0（见 [LICENSE](LICENSE)）。

> 本项目按发布选择**移除了上游 `const.py` 中的 CAK / C1 / C2 常量**，改为运行时由使用者自行提供。离线测试与 CI 改用伪造的测试向量。这不改变协议代码的 GPL-3.0 属性，属于下面列出的又一处实质性修改。

## 相对上游的修改（GPL-3.0 §5）

- `custom_components/huawei_scale3/__init__.py`：清空后重写，移除所有 Home Assistant 导入，使协议包可独立运行。
- `custom_components/huawei_scale3/session.py`：`_drain_history()` 增加 INFO/DEBUG 诊断日志，用于区分「秤回复空包」「超时」「解析失败」。
- `custom_components/huawei_scale3/const.py`：删除内置 CAK / C1 / C2 常量，改为占位说明与配置指引。
- `selftest.py`：改用伪造测试向量，不再依赖任何真实设备密钥。
- `tests/test_protocol.py`：设备级 C1 / C2 改为默认伪造向量；真实值可用 `HUAWEI_TEST_C1` / `HUAWEI_TEST_C2` 环境变量注入，以复现对公开抓包的逐字节比对。会话级密文仍是 openScale 公开抓包里的单次派生值，不是设备密钥。
- 新增的原创文件：`weigh.py`、`watch.py`、`scan.py`、`probe_direct.py`、`recompute.py`、`selftest.py`、`start_watch.bat`、`pytest.ini`、`requirements.txt`、`.github/workflows/ci.yml`、本文档与 `README.md`。
- 其余协议文件按上游原样保留（含文件头里的 GPL-3.0 / openScale 署名）。

原作者未参与本项目，也不为其背书。有问题请先在本仓库提 issue。

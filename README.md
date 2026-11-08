# huawei-scale3-pc

> **Read a HUAWEI Scale 3 (Bluetooth edition) directly from a desktop PC over BLE** — no Home Assistant, no ESP32 proxy, no rooted phone, no cloud export. Everything stays in a local CSV.
>
> 用 PC 的蓝牙直连「华为智能体脂秤 3 蓝牙版」，把体重和全套体成分写进本地 CSV。不需要 HA、不需要额外硬件、不需要 root、不需要从 App 导出。

## 为什么需要这个

Windows「设置 → 添加蓝牙设备」能扫到秤，也能配对，但配对完读不到任何数据：这台秤**没有标准体重秤服务 `181d`**，测量数据走 `181c` 下一堆私有 UUID，外面套着 HMAC 双向认证 + AES-128-CTR，密钥由华为运动健康 App 的 native 白盒库派生。华为也没出 PC 客户端。

本项目把 [Peter-Maguire/hacs-huawei-scale](https://github.com/Peter-Maguire/hacs-huawei-scale) 的 Hagrid/WSP 协议实现（源自 [openScale](https://github.com/oliexdev/openScale)）从 Home Assistant 里剥出来，换成纯 [bleak](https://github.com/hbldh/bleak) 的桌面命令行工具。**全链路已在真机跑通**：

| | |
| --- | --- |
| 设备 | `HUAWEI Scale 3 BLE-700`，`product_id = M0CJ`，固件 `2.0.0.70` |
| 主机 | Windows 11 + bleak 3.1 WinRT 后端 + 板载 BLE 适配器 |
| 流程 | 发现广播 → 枚举 37 个私有 GATT 特征 → HMAC 双向认证 → 时钟/单位/69 字节用户档案 → 实时测量帧 → CSV |
| 实测 | 体重 / 体脂率 / 阻抗全部成功解析，并与运动健康 App 显示一致 |

**输出 18 列**：体重、体脂率、心率、阻抗、水分、蛋白质、骨骼肌(kg 与 %)、骨量、去脂体重、基础代谢、内脏脂肪等级、算法体脂、计算所用档案，以及时间戳、来源、设备地址。

> 注意：体脂以外的那些**不是秤传的**。秤只上报体重 / 阻抗 / 心率 / 时间戳，其余全是运动健康 App 拿「阻抗 + 性别/年龄/身高/体重」算出来的。本项目用 openScale 拟合的同款模型在 PC 上算——实测算法体脂与秤上报值逐条完全一致，误差 0.0 个百分点。

## 快速开始

### 1. 环境

- Python 3.11+，一台带 BLE 的电脑（Windows 10/11、Linux/BlueZ、macOS 均可，bleak 都支持）
- 打开系统蓝牙开关

```bash
pip install -r requirements.txt
```

### 2. 找到你的秤

秤**只有人踩上去时才广播**。先光脚站上去，然后在另一个终端扫：

```bash
python scan.py --seconds 30 --all
```

记下 `HUAWEI Scale 3 BLE-xxx` 那行的 MAC 地址。

### 3. 配置设备、档案与密钥（都不会进 git）

> **本项目不分发 CAK / C1 / C2 协议密钥**，需要你自己提供，见下方「关于密钥」。

```bash
cp scale_config.example.json scale_config.json
```

填上 `address`、年龄、身高、性别，以及 `cak` / `c1` / `c2`。也可以完全不建文件，用环境变量或命令行：

```bash
# Windows: set HUAWEI_SCALE_MAC=AA:BB:CC:DD:EE:FF
export HUAWEI_SCALE_MAC=AA:BB:CC:DD:EE:FF
export HUAWEI_SCALE_CAK=<32 位十六进制>
export HUAWEI_SCALE_C1=<32 位十六进制>
export HUAWEI_SCALE_C2=<32 位十六进制>
python watch.py --age 30 --height 175
```

优先级：命令行参数 > 环境变量 > `scale_config.json`。
`scale_config.json` 已被 `.gitignore` 排除。代码里的 `DEFAULT_AGE = 30` / `175 cm` 只是中性的示例值，请改成你自己的。

#### 关于密钥

秤的 Hagrid/WSP 握手用 HMAC-SHA256 双向认证，需要三个 16 字节常量：CAK（App 内部 id 33）、C1 / C2（App 内部 A/B，id 1033 / 2033）。它们由华为运动健康 App 的 native 白盒库派生，不在 BLE 广播里，也无法从秤本身读出。

**本项目不内置、不分发、不描述提取步骤**。`const.py` 里只保留占位说明。如果你已有合法取得的这三个值（每个 32 位十六进制字符），填进上面任意一种配置即可；缺失时程序会直接报错并列出三种配置方式，不会尝试猜测或回退到内置值。

公开资料（[上游逆向文章](https://petermaguire.xyz/posts/huawei-scale-ble-protocol)）梳理了派生机制，[上游 HACS 集成](https://github.com/Peter-Maguire/hacs-huawei-scale) 的 GPL 代码中也含这些常量。请自行判断获取与使用的合规性。

> 离线自检与 CI 默认使用伪造的设备密钥（`selftest.py` 里的 `00 01 02 …`），**不含任何设备级 CAK / C1 / C2**。测试中保留的会话级密文来自 openScale 公开抓包，仅用于逐字节复现分帧与解密，无法用于连接设备。因此**没有硬件也能跑通全部测试**；如自己有真实 C1/C2，可用 `HUAWEI_TEST_C1` / `HUAWEI_TEST_C2` 环境变量注入以复现逐字节比对。

### 4. 启动，然后忘掉它

```bash
python watch.py
```

Windows 也可双击 `start_watch.bat`。守护持续扫描，正常上秤即可，自动追加到 `weights.csv`（按「同体重 + 秤上时间相隔 ≤90 秒」去重）。

第一次使用建议：**关掉手机蓝牙**（运动健康 App 会抢 BLE 连接）、**光脚站稳 30 秒**。

## 命令一览

| 命令 | 用途 |
| --- | --- |
| `python watch.py` | 常驻守护，日常推荐 |
| `python weigh.py --address <MAC> --history` | 单次连接读数，实时失败自动兜底读历史 |
| `python weigh.py --history-only` | 只认证 + 读秤内历史，踩一下唤醒就够 |
| `python scan.py --all --seconds 30` | 扫描并打印所有 BLE 广播（排查物理层） |
| `python recompute.py --age 30` | 换档案重算所有历史记录的体成分列 |
| `python selftest.py` | 用模拟秤离线跑完整握手，无需硬件 |
| `python -m pytest -q` | 49 个协议单测 |
| `python probe_direct.py` | 验证能否按 MAC 绕过广播直连（结论：不能，见下） |

## 实测踩过的坑

1. **广播窗口约 1 分钟**：实测 9 条广播、持续 76 秒、RSSI 从 -84 升到 -44（人走近并站上去），测完秤就睡眠彻底停播。所以不能和电脑「对表」，只能常驻扫描；守护空轮只歇 5 秒避免漏窗口，成功一轮后歇 90 秒避免人还站在秤上被反复连接。
2. **半成品帧**：体成分没测完时帧里没有阻抗，体脂会被解析成 0。程序以阻抗判断帧是否完整，无阻抗时体脂留空、不写噪声行。
3. **Windows 不会缓存未配对的 BLE 设备**：按 MAC 直连永远 `BleakDeviceNotFoundError`，哪怕 GATT 刚成功连过一次。任何时候都得踩秤唤醒，无法随时抽读。
4. **秤内读不到历史**：写空包触发 `CHR_HISTORY_WEIGHT` 后，秤立刻回 `len=0` 空包，明确表示没有离线记录。华为官网说的「最多 500 组历史」是**运动健康 App 体重管理卡片的容量**，不是秤内存储。要全量历史请走 App 或华为隐私中心申请数据副本。
5. **手机 App 抢连接**：称重时关掉手机蓝牙。
6. 目前只在**一台** Scale 3 蓝牙版（`M0CJ / 2.0.0.70`）上验证过。Scale 3 Pro、Scale 2 Pro、荣耀秤协议相近但行为不同，故意不匹配。

## 体成分算法

`custom_components/huawei_scale3/body_composition.py`：openScale 从 `HuaweiScale3BodyComposition.kt` 移植的四电极模型，特征向量 `[h²/z, z, w, h, age², age, 1]`，男女各一套系数，拟合自华为 Health 的输入输出行为。仅支持成人（≥18 岁）、120–230 cm、20–250 kg、100–1000 Ω。

年龄主要影响基础代谢和内脏脂肪等级。改档案后跑 `recompute.py` 可重算全部历史，秤上报的 `weight_kg` / `fat_percent` / `impedance_ohm` 一个字节都不改。

## 许可证与合规

- 本项目为 **GPL-3.0**（见 [LICENSE](LICENSE)），因为协议代码派生自同为 GPL-3.0 的 openScale 与 hacs-huawei-scale。署名、来源和「相对上游的修改」见 [CREDITS.md](CREDITS.md)。
- **本项目不分发 CAK / C1 / C2**。这三个 16 字节常量派生自华为运动健康 App 的 native 白盒库，使用者需自行合法获取，并通过 `scale_config.json`、环境变量或 `--cak / --c1 / --c2` 提供；`const.py` 只保留占位说明。使用前请自行评估所在地区的法律与条款风险。
- **非华为官方项目**，与华为无关联。仅用于读取你自己的秤、你自己的数据。
- 所有数据只写本地 `weights.csv`，不联网、不上传、无遥测。`weights.csv`、广播日志、GATT dump 均已在 `.gitignore` 中排除。仓库里的 `weights.example.csv` 是虚构数据。

## 状态

- [x] Windows 11 真机端到端读数（实时帧）
- [x] 49 个协议单测 + 模拟秤端到端自检
- [ ] Linux / macOS 真机验证（bleak 支持，未实测）
- [ ] 其他固件版本与型号

欢迎提 issue，尤其是其他型号/固件上的实测结果。

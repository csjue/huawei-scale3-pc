"""不依赖广播，按 MAC 直接发起 GATT 连接。

用于验证 Windows WinRT 蓝牙栈是否缓存了这台秤（即使它当前没在广播，
也能凭 BluetoothLEDevice.FromBluetoothAddressAsync 连上并读历史记录）。

实测结论：华为 Scale 3 蓝牙版**无法**这样直连。Windows 不会因为 GATT
连过一次就缓存未配对的 BLE 设备，永远返回 BleakDeviceNotFoundError。
必须踩秤唤醒。保留此脚本供其他平台/型号验证。
"""

import argparse
import asyncio
import sys

from bleak import BleakClient

import local_config


async def probe(address: str, timeout: float) -> int:
    print(f"按 MAC 直连 {address}（不等广播）...", flush=True)
    client = BleakClient(address, timeout=timeout)
    try:
        await asyncio.wait_for(client.connect(), timeout=timeout + 5)
    except Exception as err:  # noqa: BLE001
        print(f"直连失败: {type(err).__name__}: {err}", flush=True)
        print(
            "结论: Windows 没有缓存这台秤，或它当前不在广播/已被手机占用。"
            "必须踩秤唤醒。",
            flush=True,
        )
        return 1

    print(f"连接成功! is_connected={client.is_connected}", flush=True)
    try:
        services = list(client.services)
        print(f"枚举到 {len(services)} 个服务:", flush=True)
        for svc in services:
            print(f"  {svc.uuid}  ({len(svc.characteristics)} chars)", flush=True)
        has_hagrid = any(
            "02b2a08e" in ch.uuid.lower()
            for svc in services
            for ch in svc.characteristics
        )
        print(f"Hagrid 私有特征: {'有' if has_hagrid else '无'}", flush=True)
        return 0
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="按 MAC 直连华为体脂秤探测")
    ap.add_argument("--address", default=None, help="秤的 BLE MAC，默认读本地配置")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()
    address = local_config.resolve_address(args.address)
    if not address:
        print(local_config.missing_address_hint(), file=sys.stderr)
        return 2
    try:
        return asyncio.run(probe(address, args.timeout))
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

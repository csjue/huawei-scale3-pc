"""扫描本机 BLE 广播，找华为智能体脂秤 3（蓝牙版）。

用法：
    python scan.py                    # 扫描 12 秒
    python scan.py --seconds 60 --all

秤只在有人站上去时才广播，所以扫描时请先踩上秤（或用手压住 >5kg）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from bleak import BleakScanner

from custom_components.huawei_scale3 import protocol as p


def _is_huawei_scale(name: str) -> bool:
    upper = (name or "").upper()
    return any(k in upper for k in ("HUAWEI", "HONOR", "SCALE", "HAG", "DOBBY", "LUP", "M0C"))


async def scan(seconds: float, show_all: bool, log_path: str | None) -> int:
    seen: dict[str, str] = {}
    hits: list[str] = []
    log = open(log_path, "a", encoding="utf-8") if log_path else None

    def on_advert(device, adv) -> None:
        name = device.name or adv.local_name or ""
        address = device.address
        first = address not in seen
        seen[address] = name
        md = {str(k): v.hex() for k, v in (adv.manufacturer_data or {}).items()}
        sd = {str(k): bytes(v).hex() for k, v in (adv.service_data or {}).items()}
        services = list(adv.service_uuids or [])
        if log:
            log.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "address": address,
                        "name": name,
                        "rssi": adv.rssi,
                        "manufacturer_data": md,
                        "service_data": sd,
                        "service_uuids": services,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            log.flush()
        candidate = _is_huawei_scale(name)
        matched = p.identify_scale_3(
            name,
            dict(adv.manufacturer_data or {}),
            {str(k): bytes(v) for k, v in (adv.service_data or {}).items()},
        )
        if candidate or matched:
            line = (
                f"[MATCH] {name!r} addr={address} rssi={adv.rssi} "
                f"official_identify={matched} manufacturer={md} "
                f"service_data={sd} services={services}"
            )
            if first:
                print(line, flush=True)
            if matched and address not in hits:
                hits.append(address)
        elif show_all and first:
            print(
                f"        {name!r:34} addr={address} rssi={adv.rssi} "
                f"md={md} services={services}",
                flush=True,
            )

    print(f"开始扫描 {seconds:.0f} 秒 ... （全量记录，秤需要有人站上去才会广播）", flush=True)
    scanner = BleakScanner(detection_callback=on_advert)
    try:
        await scanner.start()
    except Exception as err:
        print(f"蓝牙扫描启动失败: {type(err).__name__}: {err}", file=sys.stderr)
        print("检查：Windows 设置里的蓝牙开关是否打开；蓝牙支持服务 bthserv 是否运行。", file=sys.stderr)
        if log:
            log.close()
        return 3
    try:
        await asyncio.sleep(seconds)
    finally:
        await scanner.stop()
        if log:
            log.close()

    print(f"\n共发现 {len(seen)} 个 BLE 设备。", flush=True)
    if hits:
        print("识别为华为 Scale 3 的设备：")
        for addr in hits:
            print(f"  {addr}  {seen[addr]}")
        print("\n下一步：python weigh.py --address " + hits[0])
        return 0
    print("没发现华为 Scale 3。对比 scan_log.jsonl 看期间有没有新出现的设备。", flush=True)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描华为体脂秤 3 的 BLE 广播")
    ap.add_argument("--seconds", type=float, default=12.0, help="扫描时长（秒）")
    ap.add_argument("--all", action="store_true", help="打印所有发现的设备")
    ap.add_argument("--log", default="scan_log.jsonl", help="全量广播日志（jsonl，追加写）")
    args = ap.parse_args()
    return asyncio.run(scan(args.seconds, args.all, args.log))


if __name__ == "__main__":
    raise SystemExit(main())

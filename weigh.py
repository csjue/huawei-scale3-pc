"""用 PC 蓝牙直连华为智能体脂秤 3，完成认证并读一次称重。

协议层来自 Peter-Maguire/hacs-huawei-scale（GPL-3.0，基于 openScale 的
Huawei Hagrid WSP 驱动），这里只把 bleak 客户端适配成它期望的接口。

用法：
    python weigh.py                       # 守候 240 秒，踩上秤后自动读数
    python weigh.py --wait 600            # 守候更久
    python weigh.py --address AA:BB:CC:DD:EE:FF
    python weigh.py --inspect-only        # 只枚举 GATT，不做认证握手
    python weigh.py --history             # 顺带补读秤里存的历史记录

运行时请光脚站上秤并站稳 20-30 秒：秤只在有人踩着的时候广播。
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

from custom_components.huawei_scale3 import body_composition as bc
from custom_components.huawei_scale3 import protocol as p
from custom_components.huawei_scale3 import session as s

# 示例用户档案：既用于下发给秤的 69 字节 SET_USER_INFO，也用于 App 同款体成分算法。
# 这两行只是仓库里的中性示例值。真实档案请写进 gitignored 的 scale_config.json，
# 或传 --age / --height；历史记录可用 recompute.py 重算。
DEFAULT_AGE = 30
DEFAULT_HEIGHT_CM = 175.0

# 秤只上报体重/阻抗/心率；水分、蛋白质、骨骼肌等体成分指标是
# 运动健康 App 用阻抗 + 用户档案算出来的（openScale 逆向拟合的系数）。
CSV_FIELDS = [
    "logged_at", "measured_at", "weight_kg", "fat_percent", "heart_rate",
    "impedance_ohm", "live", "address",
    "water_percent", "protein_percent", "skeletal_muscle_kg",
    "skeletal_muscle_percent", "bone_mineral_kg", "lean_body_mass_kg",
    "bmr_kcal", "visceral_fat_level", "algo_fat_percent", "profile",
]
BODY_FIELDS = CSV_FIELDS[8:]


def composition_fields(
    weight_kg: float, impedance_ohm: float | None, args: argparse.Namespace
) -> dict:
    """用阻抗 + 用户档案算出 App 里那些体成分指标；无阻抗时返回空列。"""
    extra = {key: "" for key in BODY_FIELDS}
    if not impedance_ohm:
        return extra
    comp = bc.calculate(
        height_cm=args.height,
        weight_kg=weight_kg,
        age_years=args.age,
        male=not args.female,
        impedance_ohm=impedance_ohm,
    )
    if comp is None:
        return extra
    extra.update(
        water_percent=f"{comp.water_percent:.1f}",
        protein_percent=f"{comp.protein_percent:.1f}",
        skeletal_muscle_kg=f"{comp.skeletal_muscle_kg:.2f}",
        skeletal_muscle_percent=f"{comp.skeletal_muscle_percent:.1f}",
        bone_mineral_kg=f"{comp.bone_mineral_kg:.2f}",
        lean_body_mass_kg=f"{comp.lean_body_mass_kg:.2f}",
        bmr_kcal=f"{comp.bmr_kcal:.0f}",
        visceral_fat_level=f"{comp.visceral_fat_level:.0f}",
        algo_fat_percent=f"{comp.body_fat_percent:.1f}",
        profile=f"{'M' if not args.female else 'F'}/{args.age}/{args.height:g}",
    )
    return extra

LOG = logging.getLogger("weigh")


class BleakAdapter:
    """把 BleakClient 适配成 Scale3Session 需要的接口。

    WinRT 的通知回调可能落在线程池线程上，而 session 用的是 asyncio.Queue，
    所以这里统一把回调调度回事件循环线程。
    """

    def __init__(self, client: BleakClient, loop: asyncio.AbstractEventLoop) -> None:
        self._client = client
        self._loop = loop

    @property
    def services(self):
        return self._client.services

    async def start_notify(self, char, callback) -> None:
        def safe(sender, data) -> None:
            try:
                in_loop = asyncio.get_running_loop() is self._loop
            except RuntimeError:
                in_loop = False
            if in_loop:
                callback(sender, data)
            else:
                self._loop.call_soon_threadsafe(callback, sender, bytearray(data))

        await self._client.start_notify(char, safe)

    async def stop_notify(self, char) -> None:
        await self._client.stop_notify(char)

    async def write_gatt_char(self, char, data, response: bool = True) -> None:
        await self._client.write_gatt_char(char, data, response=response)


def dump_gatt(client: BleakClient, path: str) -> list[dict]:
    rows: list[dict] = []
    for service in client.services:
        for char in service.characteristics:
            rows.append(
                {
                    "service": str(service.uuid),
                    "characteristic": str(char.uuid),
                    "properties": list(char.properties),
                }
            )
    Path(path).write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return rows


def missing_hagrid_chars(rows: list[dict]) -> list[str]:
    present = {r["characteristic"].lower() for r in rows}
    required = (
        p.CHR_REQUEST_AUTH,
        p.CHR_AUTH_TOKEN,
        p.CHR_SEND_WORK_KEY,
        p.CHR_SET_USER_INFO,
        p.CHR_REALTIME_WEIGHT,
    )
    return [uuid for uuid in required if uuid.lower() not in present]


_NOT_SCALE = (
    "BAND", "WATCH", "BUDS", "EARPHONE", "PHONE", "MATE", "PAD",
    "SPEAKER", "HEADSET", "MOUSE", "KEYBOARD", "GPS",
)
_SCALE_MARKERS = (
    "SCALE", "体脂", "体重", "HAG", "DOBBY", "LUP", "M0C", "M00D",
    "M00F", "HEM-B19", "HERM-B19", "N001", "007B", "AH100", "CH100",
)


def save_advert(device, adv, path: str = "advert.json") -> None:
    payload = {
        "name": device.name or adv.local_name or "",
        "address": device.address,
        "rssi": adv.rssi,
        "service_uuids": list(adv.service_uuids or []),
        "manufacturer_data": {
            str(k): v.hex() for k, v in (adv.manufacturer_data or {}).items()
        },
        "service_data": {
            str(k): bytes(v).hex() for k, v in (adv.service_data or {}).items()
        },
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def is_candidate(name: str, adv) -> bool:
    upper = (name or "").upper()
    if any(k in upper for k in _NOT_SCALE):
        return False
    if any(k in upper for k in _SCALE_MARKERS):
        return True
    return p.identify_scale_3(
        name,
        dict(adv.manufacturer_data or {}),
        {str(k): bytes(v) for k, v in (adv.service_data or {}).items()},
    )


async def wait_for_scale(
    seconds: float, address: str | None, excluded: set[str], log_path: str | None
):
    loop = asyncio.get_running_loop()
    found: asyncio.Future = loop.create_future()
    announced: set[str] = set()
    log = open(log_path, "a", encoding="utf-8") if log_path else None

    def on_advert(device, adv) -> None:
        name = device.name or adv.local_name or ""
        md = {str(k): v.hex() for k, v in (adv.manufacturer_data or {}).items()}
        sd = {str(k): bytes(v).hex() for k, v in (adv.service_data or {}).items()}
        services = list(adv.service_uuids or [])
        if log:
            log.write(
                json.dumps(
                    {
                        "ts": loop.time(),
                        "address": device.address,
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
        if device.address not in announced:
            announced.add(device.address)
            print(
                f"  [空气] {name!r:28} {device.address} rssi={adv.rssi} "
                f"md={md} services={services}",
                flush=True,
            )
        if found.done() or device.address in excluded:
            return
        ok = (
            device.address.upper() == address.upper()
            if address
            else is_candidate(name, adv)
        )
        if ok:
            print(
                f"发现候选: {name!r}  addr={device.address}  rssi={adv.rssi}\n"
                f"           manufacturer={md} service_data={sd} "
                f"services={services}",
                flush=True,
            )
            save_advert(device, adv)
            found.set_result(device)

    scanner = BleakScanner(detection_callback=on_advert)
    await scanner.start()
    try:
        return await asyncio.wait_for(found, timeout=seconds)
    except TimeoutError:
        return None
    finally:
        await scanner.stop()
        if log:
            log.close()


def _row_time(row: dict) -> datetime | None:
    raw = row.get("measured_at") or row.get("logged_at") or ""
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def append_csv(path: str, rows: list[dict]) -> int:
    target = Path(path)
    new_file = not target.exists() or target.stat().st_size == 0
    fields = CSV_FIELDS
    old_rows: list[dict] = []
    if not new_file:
        with target.open("r", newline="", encoding="utf-8-sig") as handle:
            old_rows = list(csv.DictReader(handle))
    exact = {
        (old.get("measured_at", ""), old.get("weight_kg", ""))
        for old in old_rows
    }

    def duplicate(row: dict) -> bool:
        if (row["measured_at"], row["weight_kg"]) in exact:
            return True
        # 同一次称重会被守护反复连上、抓到多帧（秤上时间差几秒~几十秒）；
        # 同体重且相隔 90 秒内视为同一次，只留第一条（通常是最完整的那帧）。
        stamp = _row_time(row)
        if stamp is None:
            return False
        return any(
            old.get("weight_kg") == row["weight_kg"]
            and (prev := _row_time(old)) is not None
            and abs((stamp - prev).total_seconds()) <= 90
            for old in old_rows
        )

    fresh = [row for row in rows if not duplicate(row)]
    if not fresh:
        return 0

    # Excel/WPS 等编辑器保存 CSV 时会去掉 BOM 和末行换行；直接追加会把
    # 两条记录粘成一行。追加前先补行尾，并且只有新建文件才用 utf-8-sig
    # （否则每次 open 都可能在文件中间再写一个 BOM）。
    if not new_file:
        with target.open("rb") as handle:
            handle.seek(-1, 2)
            tail = handle.read(1)
        if tail not in (b"\n", b"\r"):
            with target.open("ab") as handle:
                handle.write(b"\r\n")

    encoding = "utf-8-sig" if new_file else "utf-8"
    mode = "w" if new_file else "a"
    with target.open(mode, newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if new_file:
            writer.writeheader()
        writer.writerows(fresh)
    return len(fresh)


async def history_only(sess: s.Scale3Session) -> None:
    """认证后直接读秤内存储的记录，不等实时称重（几秒完成）。"""
    await sess._subscribe(s._PHASE_AUTH)
    await sess._authenticate()
    await sess._subscribe(s._PHASE_SYNC)
    await sess._sync_clock_and_profile()
    await sess._subscribe(s._PHASE_HISTORY)
    await sess._drain_history()


async def history_after_failure(sess: s.Scale3Session) -> None:
    """实时测量失败后，连接和 work key 还在，直接补读秤内记录。"""
    await sess._subscribe(s._PHASE_HISTORY)
    await sess._drain_history()


async def handle_device(args: argparse.Namespace, device) -> int:
    loop = asyncio.get_running_loop()
    session_box: dict[str, s.Scale3Session] = {}

    def on_disconnect(_client) -> None:
        sess = session_box.get("sess")
        if sess is not None:
            loop.call_soon_threadsafe(sess.notify_disconnected)

    client = BleakClient(device, disconnected_callback=on_disconnect, timeout=30)
    try:
        await client.connect()
    except Exception as err:
        print(f"连接失败: {type(err).__name__}: {err}", file=sys.stderr)
        print("Windows 上若反复失败，可先在 设置-蓝牙 里手动配对一次再试。", file=sys.stderr)
        return 3

    try:
        print("已连接，正在枚举 GATT ...", flush=True)
        gatt = dump_gatt(client, args.gatt_dump)
        print(f"  {len(gatt)} 个特征值，已写入 {args.gatt_dump}", flush=True)
        missing = missing_hagrid_chars(gatt)
        print(f"  Hagrid 私有布局缺失项: {missing or '无'}", flush=True)
        if missing:
            fff = [r for r in gatt if "fff" in r["service"].lower()]
            print(
                "  这台设备没有华为 Hagrid 私有 GATT，跳过。"
                + (" 检测到 fff0/fff1 系列 → Chipsea/OKOK 明文方案，体重可能在广播里。" if fff else ""),
                flush=True,
            )
            print(f"  服务 UUID: {sorted({r['service'] for r in gatt})}", flush=True)
            return 4
        if args.inspect_only:
            print("  --inspect-only：GATT 匹配，协议可用，未执行握手。", flush=True)
            return 0

        secrets = s.Secrets.from_hex(args.cak, args.c1, args.c2)
        user = s.ScaleUser(
            user_id=args.user_id,
            male=not args.female,
            age=args.age,
            height_cm=args.height,
            weight_kg=args.weight,
        )
        rows: list[dict] = []

        def on_measurement(m: p.WeightMeasurement, live: bool) -> None:
            stamp = m.timestamp.isoformat(sep=" ") if m.timestamp else ""
            # 没有阻抗 = 体脂测量没完成，此时 fat_percent 是解析出的 0，不是真实值。
            fat_valid = bool(m.impedance_ohm) and (m.fat_percent or 0) > 0
            fat_text = f"{m.fat_percent:.1f}%" if fat_valid else "-"
            extra = composition_fields(m.weight_kg, m.impedance_ohm, args)
            print(
                f"  {'[实时]' if live else '[历史]'} "
                f"体重 {m.weight_kg:.2f} kg | 体脂 {fat_text} | "
                f"心率 {m.heart_rate or '-'} | 阻抗 {m.impedance_ohm or '-'} Ω | "
                f"秤上时间 {stamp or '-'}",
                flush=True,
            )
            if extra["water_percent"]:
                print(
                    f"    ├ 水分 {extra['water_percent']}% | 蛋白质 "
                    f"{extra['protein_percent']}% | 骨骼肌 "
                    f"{extra['skeletal_muscle_kg']} kg "
                    f"({extra['skeletal_muscle_percent']}%) | 骨量 "
                    f"{extra['bone_mineral_kg']} kg",
                    flush=True,
                )
                print(
                    f"    └ 去脂体重 {extra['lean_body_mass_kg']} kg | 基础代谢 "
                    f"{extra['bmr_kcal']} kcal | 内脏脂肪 "
                    f"{extra['visceral_fat_level']} 级 | 算法体脂 "
                    f"{extra['algo_fat_percent']}%（秤报 {fat_text}）",
                    flush=True,
                )
            rows.append(
                {
                    "logged_at": datetime.now().isoformat(timespec="seconds"),
                    "measured_at": stamp,
                    "weight_kg": f"{m.weight_kg:.2f}",
                    "fat_percent": f"{m.fat_percent:.1f}" if fat_valid else "",
                    "heart_rate": m.heart_rate or "",
                    "impedance_ohm": m.impedance_ohm or "",
                    "live": int(live),
                    "address": device.address,
                    **extra,
                }
            )

        def on_state(state: str) -> None:
            print(f"  state: {state}", flush=True)
            if state == "measuring":
                print(
                    "  >>> 已进入测量：请光脚站稳，至少再保持 30 秒别下来 <<<",
                    flush=True,
                )
                try:
                    import winsound

                    for _ in range(3):
                        winsound.Beep(880, 160)
                except Exception:
                    print("\a", end="", flush=True)

        def on_info(key: str, value: str) -> None:
            print(f"  info: {key} = {value}", flush=True)

        adapter = BleakAdapter(client, loop)
        sess = s.Scale3Session(
            adapter,
            device.address,
            secrets,
            user,
            read_history=args.history,
            metric=True,
            on_measurement=on_measurement,
            on_state=on_state,
            on_info=on_info,
        )
        session_box["sess"] = sess
        try:
            if args.history_only:
                print("  历史模式：认证后直接读秤内记录，不需要一直站着。", flush=True)
                await asyncio.wait_for(history_only(sess), timeout=args.timeout)
            else:
                try:
                    await asyncio.wait_for(sess.run(), timeout=args.timeout)
                except TimeoutError:
                    print("  实时测量超时，改读秤内历史 ...", flush=True)
                    if not rows:
                        await asyncio.wait_for(history_after_failure(sess), timeout=60)
                except s.SessionError as err:
                    print(f"  实时测量未完成：{err}", flush=True)
                    print("  改读秤内历史 ...", flush=True)
                    if not rows:
                        await asyncio.wait_for(history_after_failure(sess), timeout=60)
        except s.AuthenticationError as err:
            print(f"认证失败：{err}", file=sys.stderr)
            print(
                "说明提供的 CAK/C1/C2 与这台秤的固件不匹配，"
                "请核对 scale_config.json、环境变量或 --cak/--c1/--c2。",
                file=sys.stderr,
            )
            return 5
        except TimeoutError:
            print("整体超时，检查下面有没有读到数据。", file=sys.stderr)
        except s.SessionError as err:
            print(f"会话失败：{err}", file=sys.stderr)

        if rows:
            added = append_csv(args.csv, rows)
            print(f"\n读到 {len(rows)} 条，新增 {added} 条已写入 {args.csv}", flush=True)
            return 0
        print("没拿到测量数据。", flush=True)
        return 6
    finally:
        await client.disconnect()


def validate_secrets(args: argparse.Namespace) -> str | None:
    """Not shipped with the project: users must bring their own 16-byte keys."""
    missing = [n for n in ("cak", "c1", "c2") if not getattr(args, n, None)]
    if missing:
        return (
            "缺少协议密钥 " + ", ".join("--" + n for n in missing) + "。\n"
            "本项目不分发 CAK / C1 / C2（每个是 32 位十六进制字符串 = 16 字节）。\n"
            "请任选一种方式提供：\n"
            "  1) 在 gitignored 的 scale_config.json 里填 cak / c1 / c2\n"
            "  2) 设置环境变量 HUAWEI_SCALE_CAK / HUAWEI_SCALE_C1 / HUAWEI_SCALE_C2\n"
            "  3) 命令行传 --cak xxx --c1 xxx --c2 xxx\n"
            "密钥需自行从设备/华为运动健康 App 获取，参见 README「关于密钥」。"
        )
    for name in ("cak", "c1", "c2"):
        raw = getattr(args, name)
        try:
            if len(bytes.fromhex(raw)) != 16:
                raise ValueError
        except ValueError:
            return f"--{name} 必须是 32 位十六进制字符串（16 字节），当前值不合法。"
    return None


def setup_history_logging(args: argparse.Namespace) -> None:
    """只把 session 模块里 ``history:`` 开头的诊断打到终端，不惊动 bleak 日志。"""
    if args.debug:
        return  # root 已开 DEBUG，交给 basicConfig
    logger = logging.getLogger("custom_components.huawei_scale3.session")
    if not any(getattr(h, "_history_probe", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("  [history] %(message)s"))
        handler.addFilter(lambda rec: rec.getMessage().startswith("history:"))
        handler._history_probe = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(logging.DEBUG)


async def run(args: argparse.Namespace) -> int:
    problem = validate_secrets(args)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    setup_history_logging(args)
    print(
        f"守候 {args.wait:.0f} 秒 ... 现在请光脚站上秤，站稳 20-30 秒别下来。",
        flush=True,
    )
    excluded: set[str] = set()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + args.wait
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            print("超时：没等到秤。确认秤有电、有人站着，或加长 --wait。", flush=True)
            return 2
        device = await wait_for_scale(remaining, args.address, excluded, args.advert_log)
        if device is None:
            print("超时：没等到秤。", flush=True)
            return 2
        result = await handle_device(args, device)
        if result == 0:
            return 0
        if not args.address:
            excluded.add(device.address)
        print("  继续等待真正的秤 ...", flush=True)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="PC 蓝牙直连华为体脂秤 3 读数")
    ap.add_argument("--wait", type=float, default=240.0, help="等秤广播的秒数")
    ap.add_argument("--address", default=None, help="指定秤的蓝牙 MAC（跳过自动发现）")
    ap.add_argument("--timeout", type=float, default=150.0, help="单次会话总超时")
    ap.add_argument("--inspect-only", action="store_true", help="只枚举 GATT 并验证协议")
    ap.add_argument("--history", action="store_true", help="实时读完后补读秤内存储的历史记录")
    ap.add_argument("--history-only", action="store_true", help="只认证+读秤内历史，不等实时称重")
    ap.add_argument("--csv", default="weights.csv", help="结果 CSV 路径（追加写）")
    ap.add_argument("--gatt-dump", default="gatt_dump.json", help="GATT 清单输出路径")
    ap.add_argument("--advert-log", default="advert_log.jsonl", help="全量广播日志（jsonl）")
    ap.add_argument("--user-id", type=int, default=1)
    ap.add_argument("--female", action="store_true", help="默认按男性下发档案")
    ap.add_argument("--age", type=int, default=DEFAULT_AGE, help="年龄，用于体脂算法")
    ap.add_argument("--height", type=float, default=DEFAULT_HEIGHT_CM, help="身高 cm，用于体脂算法")
    ap.add_argument("--weight", type=float, default=0.0, help="上次体重 kg，0 表示不提供")
    ap.add_argument("--cak", default=None, help="16 字节 CAK，32 位 hex（本项目不内置）")
    ap.add_argument("--c1", default=None, help="16 字节 C1，32 位 hex（本项目不内置）")
    ap.add_argument("--c2", default=None, help="16 字节 C2，32 位 hex（本项目不内置）")
    ap.add_argument("--debug", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s %(message)s")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""常驻守护：每次上秤自动把数据写进 weights.csv，不用和电脑对表。

秤只在「上秤测量期间」持续广播约 1 分钟，之后进入睡眠彻底停播，所以守护
几乎不间断地扫描；发现广播就连接、认证、读实时数据（失败则尝试读秤内
历史）、去重写入 CSV，短暂冷却后继续守下一次。

MAC 地址从 --address / HUAWEI_SCALE_MAC / scale_config.json 读取，不写死在代码里。
"""
from __future__ import annotations

import asyncio
import logging
import sys

import local_config
import weigh


async def main() -> int:
    ap = weigh.build_parser()
    ap.set_defaults(
        wait=300.0,
        timeout=130.0,
        history=True,
        csv="weights.csv",
        advert_log="advert_log.jsonl",
    )
    local_config.apply_local_config(ap)
    # 空轮要立刻续上（秤的广播窗口只有 ~76 秒，冷却太长会形成盲区）；
    # 成功一轮后则等久一点，避免人还站在秤上时被反复连接、抓到半成品帧。
    ap.add_argument("--cooldown", type=float, default=5.0, help="空轮之间的冷却秒数")
    ap.add_argument(
        "--success-cooldown", type=float, default=90.0, help="成功读到数据后的冷却秒数"
    )
    args = ap.parse_args()
    args.address = local_config.resolve_address(args.address)
    if not args.address:
        print(local_config.missing_address_hint(), file=sys.stderr)
        return 2
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s %(message)s")

    print(
        f"常驻守护已启动，目标 {args.address}，结果写入 {args.csv}。\n"
        "正常上秤即可（光脚站稳 30 秒最佳），不需要盯着屏幕。Ctrl+C 退出。",
        flush=True,
    )
    while True:
        try:
            rc = await weigh.run(args)
        except Exception as err:  # noqa: BLE001 - keep the watcher alive
            print(f"[watch] 本轮异常：{type(err).__name__}: {err}", flush=True)
            rc = -1
        rest = args.success_cooldown if rc == 0 else args.cooldown
        print(
            f"[watch] 本轮结束 (rc={rc})，{rest:.0f} 秒后继续守候 ...",
            flush=True,
        )
        await asyncio.sleep(rest)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n已退出。")

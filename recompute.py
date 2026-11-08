"""按指定用户档案重算 weights.csv 里的体成分列。

秤只上报体重和阻抗；水分、蛋白质、骨骼肌、骨量、基础代谢、内脏脂肪都是
App 用「阻抗 + 性别/年龄/身高」算出来的。改了档案（尤其是年龄）后跑一次，
历史记录会全部重算，不需要重新称重。

    python recompute.py --age 30
    python recompute.py --age 30 --height 175 --female
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import local_config
import weigh


def main() -> int:
    ap = argparse.ArgumentParser(description="重算称重记录的体成分指标")
    ap.add_argument("--csv", default="weights.csv")
    ap.add_argument("--age", type=int, default=weigh.DEFAULT_AGE, help="年龄（<18 算法不支持）")
    ap.add_argument("--height", type=float, default=weigh.DEFAULT_HEIGHT_CM, help="身高 cm")
    ap.add_argument("--female", action="store_true", help="默认按男性计算")
    local_config.apply_local_config(ap)
    args = ap.parse_args()

    args.female = bool(args.female)
    path = Path(args.csv)
    if not path.exists():
        print(f"找不到 {path}")
        return 1

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("CSV 里没有记录")
        return 1

    done = 0
    for row in rows:
        try:
            weight = float(row["weight_kg"])
            impedance = float(row["impedance_ohm"])
        except (KeyError, TypeError, ValueError):
            for key in weigh.BODY_FIELDS:
                row[key] = ""
            continue
        row.update(weigh.composition_fields(weight, impedance, args))
        if row.get("water_percent"):
            done += 1

    # 先写临时文件再原子替换：避免 Excel / 预览面板占用时截断原 CSV，
    # 也避免与正在运行的 watch.py 并发写入时产生半截文件。
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=weigh.CSV_FIELDS, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    except PermissionError as err:
        tmp.unlink(missing_ok=True)
        print(
            f"写入失败：{path} 可能被 Excel / 预览窗口占用，请关闭后重试。\n"
            f"原文件未被修改。（{err}）"
        )
        return 3

    profile = f"{'F' if args.female else 'M'}/{args.age}/{args.height:g}"
    print(f"已按档案 {profile} 重算 {done}/{len(rows)} 条 → {path}")
    print("注意：这只改体成分列，秤上报的 weight_kg / fat_percent / impedance_ohm 不变。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

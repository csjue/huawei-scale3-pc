"""离线自检：用模拟秤走一遍 weigh.py 的适配层 + 完整协议握手。

不需要真秤、不需要蓝牙，用来确认 Windows / Python 3.13 上协议栈可跑通。
"""
from __future__ import annotations

import asyncio
import sys

from custom_components.huawei_scale3 import session as s
from tests.fake_scale import FakeScale
from weigh import BleakAdapter

ADDRESS = "AA:BB:CC:DD:EE:FF"

# Obviously fake test vectors, NOT device secrets. Both sides of the simulated
# handshake use these, so authentication stays self-consistent.
TEST_CAK = "000102030405060708090A0B0C0D0E0F"
TEST_C1 = "101112131415161718191A1B1C1D1E1F"
TEST_C2 = "202122232425262728292A2B2C2D2E2F"


async def main() -> int:
    secrets = s.Secrets.from_hex(TEST_CAK, TEST_C1, TEST_C2)
    fake = FakeScale(ADDRESS, secrets)
    adapter = BleakAdapter(fake, asyncio.get_running_loop())
    user = s.ScaleUser(user_id=1, male=True, age=26, height_cm=175.0, weight_kg=0.0)
    readings: list[float] = []
    states: list[str] = []

    sess = s.Scale3Session(
        adapter,
        ADDRESS,
        secrets,
        user,
        on_measurement=lambda m, live: readings.append(m.weight_kg),
        on_state=states.append,
    )
    await sess.run()
    print(f"握手状态: {' -> '.join(states)}")
    print(f"认证通过: {fake.authenticated}")
    print(f"用户档案已下发: {len(fake.user_info or b'')} 字节")
    print(f"读到体重: {readings}")
    ok = fake.authenticated and readings == [86.25]
    print("自检结果:", "通过" if ok else "失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

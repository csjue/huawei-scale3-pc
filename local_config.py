"""Resolve your scale's address and body profile without committing personal data.

Priority (high to low): explicit CLI flag > ``HUAWEI_SCALE_MAC`` env var >
``scale_config.json`` (gitignored) > argparse defaults. This keeps MAC addresses
and personal body profiles out of the repository while still allowing a
zero-argument ``python watch.py`` on your own machine.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL_FILE = HERE / "scale_config.json"
EXAMPLE_FILE = HERE / "scale_config.example.json"
PLACEHOLDER = "AA:BB:CC:DD:EE:FF"
ENV_ADDRESS = "HUAWEI_SCALE_MAC"
ENV_SECRETS = {
    "cak": "HUAWEI_SCALE_CAK",
    "c1": "HUAWEI_SCALE_C1",
    "c2": "HUAWEI_SCALE_C2",
}


def read_config() -> dict:
    """Read the gitignored local config; a broken file is ignored, not fatal."""
    if not LOCAL_FILE.exists():
        return {}
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve_address(cli_address: str | None = None) -> str | None:
    addr = cli_address or os.environ.get(ENV_ADDRESS) or read_config().get("address")
    if not addr or not isinstance(addr, str):
        return None
    addr = addr.strip().upper()
    if addr == PLACEHOLDER:
        return None  # still the example value
    return addr


def apply_local_config(ap: argparse.ArgumentParser, cfg: dict | None = None) -> None:
    """Apply profile AND protocol secrets as argparse defaults (CLI flags still win).

    Secrets are never stored in the repository: they come from the environment
    or the gitignored ``scale_config.json``.
    """
    cfg = read_config() if cfg is None else cfg
    defaults: dict = {}
    if isinstance(cfg.get("age"), int):
        defaults["age"] = cfg["age"]
    if isinstance(cfg.get("height_cm"), (int, float)):
        defaults["height"] = cfg["height_cm"]
    if isinstance(cfg.get("female"), bool):
        defaults["female"] = cfg["female"]
    for key, env in ENV_SECRETS.items():
        value = os.environ.get(env) or cfg.get(key)
        if isinstance(value, str) and value.strip():
            defaults[key] = value.strip()
    if defaults:
        ap.set_defaults(**defaults)


def missing_address_hint() -> str:
    return (
        "未配置秤的 MAC 地址。三选一：\n"
        "  1) python scan.py --seconds 30 --all        先扫出你的秤\n"
        "  2) 复制 scale_config.example.json 为 scale_config.json，填 address\n"
        f"  3) 设置环境变量 {ENV_ADDRESS}，或直接传 --address AA:BB:CC:DD:EE:FF"
    )

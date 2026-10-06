from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

CNKI_URL = "https://kns.cnki.net/kns8s/AdvSearch"


async def main_async(profile: Path, stop_flag: Path):
    profile.mkdir(parents=True, exist_ok=True)
    stop_flag.unlink(missing_ok=True)
    pw = await async_playwright().start()
    kwargs = dict(
        user_data_dir=str(profile), headless=False, accept_downloads=True,
        ignore_https_errors=True, locale="zh-CN", viewport={"width": 1440, "height": 960},
        args=["--disable-dev-shm-usage"],
    )
    ctx = None
    for channel in ("msedge", "chrome"):
        try:
            ctx = await pw.chromium.launch_persistent_context(channel=channel, **kwargs)
            break
        except Exception:
            pass
    if ctx is None:
        ctx = await pw.chromium.launch_persistent_context(**kwargs)
    try:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(CNKI_URL, wait_until="domcontentloaded", timeout=60000)
        print("LOGIN_WINDOW_READY", flush=True)
        while not stop_flag.exists():
            await asyncio.sleep(1)
    finally:
        try:
            await ctx.close()
        except Exception:
            pass
        await pw.stop()
        stop_flag.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, required=True)
    ap.add_argument("--stop-flag", type=Path, required=True)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main_async(args.profile.resolve(), args.stop_flag.resolve())))


if __name__ == "__main__":
    main()

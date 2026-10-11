from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from .browser_profile import clone_browser_profile

ROOT = Path(__file__).resolve().parents[1]
MASTER_PROFILE = ROOT / "runtime_outputs" / "cnki_master_profile"
PDF_ROOT = ROOT / "runtime_outputs" / "selected_pdfs"
_STOP = False


def request_stop_pdf() -> str:
    global _STOP
    _STOP = True
    return "已请求停止 PDF 下载；当前论文处理完成后会停止。"


def _safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(name or "download.pdf"))
    name = re.sub(r"\s+", " ", name).strip(" ._")
    return name[:180] or "download.pdf"


async def _launch_context(profile: Path):
    pw = await async_playwright().start()
    kwargs = dict(
        user_data_dir=str(profile), headless=False, accept_downloads=True,
        ignore_https_errors=True, locale="zh-CN", viewport={"width":1440,"height":960},
        args=["--disable-dev-shm-usage"],
    )
    ctx=None
    for channel in ("msedge","chrome"):
        try:
            ctx=await pw.chromium.launch_persistent_context(channel=channel,**kwargs); break
        except Exception:
            pass
    if ctx is None:
        ctx=await pw.chromium.launch_persistent_context(**kwargs)
    return pw,ctx


async def _wait_verification(page, timeout_s=600):
    elapsed=0
    while "verify/" in page.url or "安全验证" in (await page.title()):
        if elapsed >= timeout_s:
            raise RuntimeError("等待 CNKI 安全验证超时")
        await page.wait_for_timeout(1000); elapsed += 1


async def _find_download_control(page):
    selectors=[
        "#pdfDown", "a#pdfDown", ".btn-dlpdf a",
        "a:has-text('PDF下载')", "button:has-text('PDF下载')",
        "a:has-text('下载PDF')", "a:has-text('整本下载')",
        "a[href*='download']", "a[href$='.pdf']",
    ]
    for sel in selectors:
        loc=page.locator(sel)
        try: count=await loc.count()
        except Exception: continue
        for i in range(count):
            item=loc.nth(i)
            try:
                if await item.is_visible(timeout=300): return item
            except Exception:
                continue
    return None


async def _attempt_download(page, destination_dir: Path):
    control=await _find_download_control(page)
    if control is None:
        return "", "download_control_not_found"
    destination_dir.mkdir(parents=True,exist_ok=True)
    try:
        async with page.expect_download(timeout=45000) as info:
            try: await control.click(force=True)
            except Exception: await control.evaluate("e=>e.click()")
        dl=await info.value
        suggested=_safe_name(dl.suggested_filename or "download.pdf")
        target=destination_dir/suggested
        if target.exists():
            stem,suffix=target.stem,target.suffix
            n=2
            while target.exists():
                target=destination_dir/f"{stem}_{n}{suffix}"; n+=1
        await dl.save_as(target)
        if target.exists() and target.stat().st_size>0:
            return str(target),"downloaded"
        return "","empty_download"
    except PlaywrightTimeoutError:
        # Some CNKI buttons navigate to an order/download page first. Try one extra page state.
        try:
            await page.wait_for_timeout(2500)
            await _wait_verification(page,timeout_s=120)
            control2=await _find_download_control(page)
            if control2 is not None and control2 != control:
                async with page.expect_download(timeout=45000) as info:
                    try: await control2.click(force=True)
                    except Exception: await control2.evaluate("e=>e.click()")
                dl=await info.value
                target=destination_dir/_safe_name(dl.suggested_filename or "download.pdf")
                await dl.save_as(target)
                if target.exists() and target.stat().st_size>0:
                    return str(target),"downloaded_after_second_click"
        except Exception:
            pass
        return "","download_timeout_or_permission_required"
    except Exception as exc:
        return "",f"download_error:{type(exc).__name__}:{exc}"


async def download_selected_async(records: list[dict], out_dir: Path):
    global _STOP
    _STOP=False
    if not MASTER_PROFILE.exists():
        raise RuntimeError("没有 CNKI 登录资料。请先在步骤2完成登录。")
    profile=ROOT/"runtime_outputs"/"pdf_download_profile"
    clone_browser_profile(MASTER_PROFILE,profile)
    pw,ctx=await _launch_context(profile)
    rows=[]
    try:
        page=ctx.pages[0] if ctx.pages else await ctx.new_page()
        for index,rec in enumerate(records,1):
            if _STOP:
                break
            pid=str(rec.get("paper_id", "")); title=str(rec.get("title", "")); url=str(rec.get("url", ""))
            row={"paper_id":pid,"title":title,"cnki_url":url,"pdf_file":"","status":""}
            if not url:
                row["status"]="missing_cnki_url"; rows.append(row); continue
            try:
                await page.goto(url,wait_until="domcontentloaded",timeout=60000)
                await _wait_verification(page)
                pdf,status=await _attempt_download(page,out_dir)
                row["pdf_file"]=pdf; row["status"]=status
            except Exception as exc:
                row["status"]=f"error:{type(exc).__name__}:{exc}"
            rows.append(row)
        return rows
    finally:
        try: await ctx.close()
        except Exception: pass
        await pw.stop()


def download_selected(records: list[dict], out_dir: str|Path):
    return asyncio.run(download_selected_async(records,Path(out_dir)))

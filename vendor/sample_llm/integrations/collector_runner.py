"""Compatibility wrapper for the pinned cnki-metadata-exporter package.

The upstream package remains a normal installed dependency. This module only applies
small, tested KNS8 compatibility patches before delegating to the upstream native XLS
exporter. The goal is to keep Sampling Assistant's collection layer narrow and auditable.
"""
from __future__ import annotations

import re
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from cnki_metadata_exporter.exporter import CNKIMetadataExporter
from cnki_metadata_exporter.native_export import CNKINativeExporter
import cnki_metadata_exporter.exporter as exporter_mod
import cnki_metadata_exporter.native_export as native_export


async def _first_visible_locator(self, page, selectors):
    for selector in selectors:
        locator=page.locator(selector)
        try:
            count=await locator.count()
        except Exception:
            continue
        for index in range(count):
            item=locator.nth(index)
            try:
                if await item.is_visible(timeout=300):
                    return item
            except Exception:
                continue
    return None


async def _dump_search_debug(self, page, label):
    try:
        await page.screenshot(path=str(self.logs_dir/f"{label}.png"),full_page=True)
    except Exception:
        pass
    try:
        (self.logs_dir/f"{label}.html").write_text(await page.content(),encoding="utf-8")
    except Exception:
        pass


async def _launch(self):
    self.profile_dir.mkdir(parents=True,exist_ok=True)
    self._playwright=await exporter_mod.async_playwright().start()
    kwargs=dict(
        user_data_dir=str(self.profile_dir),headless=self.headless,accept_downloads=True,
        ignore_https_errors=True,locale="zh-CN",viewport={"width":1440,"height":960},
        args=["--disable-dev-shm-usage","--disable-background-timer-throttling","--disable-backgrounding-occluded-windows","--disable-renderer-backgrounding"],
    )
    for channel,label in (("msedge","Microsoft Edge"),("chrome","Google Chrome")):
        try:
            self.context=await self._playwright.chromium.launch_persistent_context(channel=channel,**kwargs)
            self.log(f"浏览器：使用系统 {label}")
            return
        except Exception as exc:
            self.log(f"系统 {label} 启动失败：{exc}")
    self.context=await self._playwright.chromium.launch_persistent_context(**kwargs)
    self.log("浏览器：使用 Playwright Chromium")


async def _open_professional_search(self,page):
    await page.goto(exporter_mod.CNKI_ADVANCED,wait_until="domcontentloaded",timeout=60000)
    await self.wait_for_human_verification(page)
    tab=await self._first_visible_locator(page,[".search-classify-menu li[name='majorSearch']","li[name='majorSearch']","[name='majorSearch']"])
    if tab is None:
        tabs=page.get_by_text("专业检索",exact=True)
        for i in range(await tabs.count()):
            item=tabs.nth(i)
            try:
                if await item.is_visible(timeout=300):
                    tab=item; break
            except Exception:
                continue
    if tab is None:
        await self._dump_search_debug(page,"professional-search-tab-missing")
        raise RuntimeError("未找到可见的知网专业检索入口")
    for attempt in range(3):
        try:
            await tab.click(force=True)
        except Exception:
            try: await tab.evaluate("e => e.click()")
            except Exception: pass
        await page.wait_for_timeout(600+attempt*500)
        box=await self._first_visible_locator(page,["textarea.textarea-major.majorSearch","textarea.majorSearch","textarea.textarea-major","#expertvalue","#txt_SearchText","textarea"])
        if box is not None:
            return
    count=await page.locator("textarea.textarea-major, textarea.majorSearch, textarea").count()
    await self._dump_search_debug(page,"professional-search-input-hidden")
    raise RuntimeError(f"专业检索标签已点击，但没有可见检索框（匹配到 {count} 个隐藏/不可见 textarea）。已保存 logs 调试文件。")


async def _set_date_control(self, locator, value: str, label: str):
    # Locator.evaluate passes the element as argument 1 and Python value as argument 2.
    # v0.4.6 inherited an incorrect ([el, value]) destructuring callback; this is the
    # tested form from the standalone selection/export diagnostic.
    script = """(el, value) => {
        el.removeAttribute('readonly');
        el.value = value;
        el.setAttribute('value', value);
        ['input','change','blur'].forEach(t => el.dispatchEvent(new Event(t,{bubbles:true})));
        if (window.jQuery) {
            try { window.jQuery(el).val(value).trigger('input').trigger('change').trigger('blur'); } catch(e) {}
        }
        return el.value;
    }"""
    try:
        await locator.evaluate(script, value)
    except Exception as exc:
        self.log(f"{label}第一次DOM写入失败：{type(exc).__name__}: {exc}；尝试 fill 兜底")
        try:
            await locator.evaluate("el => el.removeAttribute('readonly')")
            await locator.fill(value, force=True)
            await locator.dispatch_event("input")
            await locator.dispatch_event("change")
            await locator.dispatch_event("blur")
        except Exception as exc2:
            raise RuntimeError(f"{label}无法写入 {value}：{type(exc2).__name__}: {exc2}") from exc2
    current = await locator.input_value()
    self.log(f"{label}已写入：目标={value}；页面值={current}")
    return current


async def _set_publish_date_range(self, page, start_year: int | None, end_year: int | None):
    if not start_year or not end_year:
        return
    start_value = f"{int(start_year):04d}-01-01"
    end_value = f"{int(end_year):04d}-12-31"
    start_box = page.locator("#datebox0").first
    end_box = page.locator("#datebox1").first
    if not await start_box.count() or not await end_box.count():
        await self._dump_search_debug(page, "publish-date-controls-missing")
        raise RuntimeError("未找到知网发表时间控件 #datebox0 / #datebox1")
    got_start = await self._set_date_control(start_box, start_value, "发表时间起点")
    got_end = await self._set_date_control(end_box, end_value, "发表时间终点")
    if got_start != start_value or got_end != end_value:
        await self._dump_search_debug(page, "publish-date-controls-not-set")
        raise RuntimeError(f"发表时间控件写入失败：{got_start!r} -- {got_end!r}")


async def _click_search_and_wait(self, page, button):
    click_method = "normal"
    try:
        await button.click(timeout=5000)
    except Exception as exc1:
        self.log(f"普通 click 失败：{type(exc1).__name__}: {exc1}；改用 force click")
        click_method = "force"
        try:
            await button.click(force=True, timeout=5000)
        except Exception as exc2:
            self.log(f"force click 失败：{type(exc2).__name__}: {exc2}；改用 DOM click")
            click_method = "dom"
            try:
                await button.evaluate("el => el.click()")
            except Exception as exc3:
                await self._dump_search_debug(page, "search-click-failed")
                raise RuntimeError(
                    f"检索按钮三种点击方式均失败：{type(exc3).__name__}: {exc3}"
                ) from exc3
    self.log(f"已执行“检索”点击操作（method={click_method}），等待结果页")
    result = page.locator("span.pagerTitleCell, table.result-table-list, p.no-content").first
    try:
        await result.wait_for(state="visible", timeout=45000)
    except PlaywrightTimeoutError:
        await self.wait_for_human_verification(page)
        self.log("点击后45秒仍未出现结果标志，执行一次 DOM click 重试")
        try:
            await button.evaluate("el => el.click()")
            await result.wait_for(state="visible", timeout=30000)
        except Exception as exc:
            await self._dump_search_debug(page, "search-no-result-after-click")
            raise RuntimeError("检索按钮已点击，但75秒内没有出现结果表/无结果提示") from exc
    await self.wait_for_human_verification(page)
    await page.wait_for_timeout(1000)


async def _submit_professional_query(self, page, query):
    await self.open_professional_search(page)
    box = await self._first_visible_locator(
        page,
        [
            "textarea.textarea-major.majorSearch",
            "textarea.majorSearch",
            "textarea.textarea-major",
            "#expertvalue",
            "#txt_SearchText",
            "input[name='expertvalue']",
            "textarea",
        ],
    )
    if box is None:
        await self._dump_search_debug(page, "professional-search-query-box-missing")
        raise RuntimeError("未找到可见的知网专业检索式输入框")
    await box.fill(query)
    bilingual = page.locator('.gradeSearch input[data-id="EN"]:checked').first
    if await bilingual.count():
        await bilingual.uncheck()
    button = page.locator(".search-middle input.btn-search:visible, input.btn-search:visible").first
    if not await button.count():
        button = page.get_by_role("button", name=re.compile(r"检索|搜索")).first
    if not await button.count():
        raise RuntimeError("未找到知网专业检索按钮")
    await self._click_search_and_wait(page, button)


async def _submit_collection_query(self, page, collection):
    await self.open_professional_search(page)
    box = await self._first_visible_locator(
        page,
        [
            "textarea.textarea-major.majorSearch",
            "textarea.majorSearch",
            "textarea.textarea-major",
            "#expertvalue",
            "#txt_SearchText",
            "input[name='expertvalue']",
            "textarea",
        ],
    )
    if box is None:
        await self._dump_search_debug(page, "professional-search-query-box-missing")
        raise RuntimeError("未找到可见的知网专业检索式输入框")
    await box.fill(str(collection["query"]))
    self.log(f"已填写专业检索式：{collection['query']}")
    await self._set_publish_date_range(
        page, collection.get("start_year"), collection.get("end_year")
    )
    bilingual = page.locator('.gradeSearch input[data-id="EN"]:checked').first
    if await bilingual.count():
        try:
            await bilingual.uncheck()
        except Exception:
            pass
    button = page.locator(".search-middle input.btn-search:visible, input.btn-search:visible").first
    if not await button.count():
        button = page.get_by_role("button", name=re.compile(r"检索|搜索")).first
    if not await button.count():
        raise RuntimeError("未找到知网专业检索按钮")
    await self._click_search_and_wait(page, button)


async def _search_collection(self, page, collection):
    """KNS8 LY query + publication-date controls, preserving upstream retry semantics."""
    last_error = None
    for attempt in range(1, 5):
        try:
            await self._submit_collection_query(page, collection)
            total = await self.result_count(page)
            if total > 0:
                pages, per_page = await self.set_page_size_stable(page, total, 50)
            else:
                _, pages = await self.page_info(page)
                per_page = await self.current_row_count(page)
            if total > 0 and per_page > 0:
                return total, pages, per_page
            body = await self._body(page)
            self.log(
                f"{collection['id']} 第 {attempt} 次检索未读取到有效结果"
                f"（命中 {total}，当前页 {per_page} 条），准备重试"
            )
            (self.logs_dir / f"{collection['id']}-search-attempt-{attempt}.txt").write_text(
                body[:20000], encoding="utf-8"
            )
        except Exception as exc:
            last_error = exc
            self.log(f"{collection['id']} 第 {attempt} 次检索失败：{exc}")
        await page.wait_for_timeout(attempt * 3000)
    if last_error:
        raise RuntimeError(f"{collection['id']} 多次检索失败") from last_error
    raise RuntimeError(f"{collection['id']} 多次检索均未返回有效记录")




async def _select_current_page_reliable(self, page):
    """Small reliability patch for CNKI's current-page select-all control.

    CNKI can render the rows before the select-all widget's JS state is ready. We therefore
    wait for a stable row count, operate on a visible select-all control, and verify the
    selected-count before accepting success. No sampling logic is affected.
    """
    rows = await self.current_row_count(page)
    if rows == 0:
        return 0

    stable = 0
    last_rows = rows
    for _ in range(20):
        await page.wait_for_timeout(250)
        await self.wait_for_human_verification(page)
        now_rows = await self.current_row_count(page)
        if now_rows == last_rows and now_rows > 0:
            stable += 1
            if stable >= 2:
                rows = now_rows
                break
        else:
            stable = 0
            last_rows = now_rows

    before = await self.selected_count(page)
    target = before + rows
    for attempt in range(1, 4):
        checkbox = await self._first_visible_locator(
            page,
            [
                "#selectCheckAll1",
                "input[type='checkbox'][id*='selectCheckAll']",
            ],
        )
        if checkbox is None:
            await self._dump_search_debug(page, "select-all-checkbox-missing")
            raise RuntimeError("未找到可见的知网当前页全选框")

        try:
            if await checkbox.is_checked():
                await checkbox.click(force=True)
                await page.wait_for_timeout(500)
        except Exception:
            try:
                await checkbox.evaluate(
                    "e => { e.checked=false; e.dispatchEvent(new Event('change',{bubbles:true})); }"
                )
            except Exception:
                pass

        await page.wait_for_timeout(700 if attempt == 1 else 1200)
        try:
            await checkbox.click(timeout=5000)
        except Exception:
            try:
                await checkbox.click(force=True, timeout=5000)
            except Exception:
                await checkbox.evaluate("e => e.click()")

        for _ in range(40):
            await page.wait_for_timeout(250)
            await self.wait_for_human_verification(page)
            count = await self.selected_count(page)
            if count >= target:
                return count - before

        after = await self.selected_count(page)
        self.log(
            f"当前页第 {attempt} 次全选未生效（应新增 {rows}，实际新增 {after - before}），稍候重试"
        )
        if attempt < 3:
            await page.wait_for_timeout(2000 * attempt)
        if attempt == 2:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
            ready = False
            for _ in range(120):
                await page.wait_for_timeout(500)
                if "verify/" in page.url:
                    await self.wait_for_human_verification(page)
                if await self.current_row_count(page) > 0:
                    ready = True
                    break
            if not ready:
                raise RuntimeError("刷新后未恢复检索结果页")

    after = await self.selected_count(page)
    raise RuntimeError(f"当前页应新增 {rows} 条，实际新增 {after - before} 条")


# Patch the narrowest possible surface. CNKINativeExporter overrides search/select methods,
# so both base and native classes are patched where necessary.
CNKIMetadataExporter._first_visible_locator = _first_visible_locator
CNKIMetadataExporter._dump_search_debug = _dump_search_debug
CNKIMetadataExporter.launch = _launch
CNKIMetadataExporter.open_professional_search = _open_professional_search
CNKIMetadataExporter._set_date_control = _set_date_control
CNKIMetadataExporter._set_publish_date_range = _set_publish_date_range
CNKIMetadataExporter._click_search_and_wait = _click_search_and_wait
CNKIMetadataExporter.submit_professional_query = _submit_professional_query
CNKIMetadataExporter._submit_collection_query = _submit_collection_query
CNKIMetadataExporter.search_collection = _search_collection

CNKINativeExporter._first_visible_locator = _first_visible_locator
CNKINativeExporter._dump_search_debug = _dump_search_debug
CNKINativeExporter.launch = _launch
CNKINativeExporter.open_professional_search = _open_professional_search
CNKINativeExporter._set_date_control = _set_date_control
CNKINativeExporter._set_publish_date_range = _set_publish_date_range
CNKINativeExporter._click_search_and_wait = _click_search_and_wait
CNKINativeExporter.submit_professional_query = _submit_professional_query
CNKINativeExporter._submit_collection_query = _submit_collection_query
CNKINativeExporter.search_collection = _search_collection
CNKINativeExporter.select_current_page = _select_current_page_reliable

if __name__ == "__main__":
    native_export.main()

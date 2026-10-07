#!/usr/bin/env python3
"""Batch-convert text-based PDFs to information-preserving Markdown.

The converter intentionally favors complete, readable text over pixel-perfect layout.
It is tuned for Chinese academic/legal papers, but works with ordinary text PDFs too.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少 pdfplumber。请运行: python -m pip install pdfplumber") from exc


PAGE_NUMBER_RE = re.compile(r"^\s*(?:[-—–·•]\s*)?\d{1,4}(?:\s*[-—–·•])?\s*$")
DOI_RE = re.compile(r"(?:https?://doi\.org/)?10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")

H2_PATTERNS = (
    re.compile(r"^[一二三四五六七八九十百]+[、．.]\s*\S+"),
    re.compile(r"^第[一二三四五六七八九十百0-9]+[章节部分]\s*\S+"),
    re.compile(r"^(?:引言|导言|绪论|结语|结论|余论|参考文献|附录|致谢)\s*$"),
    re.compile(r"^\d+\s*[、．.]\s*[^\d].{0,45}$"),
    re.compile(r"^\d+\.\d+\s+\S.{0,45}$"),
)
H3_PATTERNS = (
    re.compile(r"^[（(][一二三四五六七八九十百]+[）)]\s*\S+"),
    re.compile(r"^\d+\.\d+\.\d+\s+\S.{0,45}$"),
)


@dataclass
class Result:
    source: str
    output: str
    status: str
    pages: int = 0
    characters: int = 0
    warnings: str = ""
    error: str = ""


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    value = value.replace("\uf0b7", "·").replace("\ue012", "")
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def metadata_map(path: Path | None) -> dict[str, dict[str, str]]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return {row.get("sample_id", "").strip(): row for row in csv.DictReader(stream)}


def sample_id(path: Path) -> str:
    match = re.match(r"([PHR]\d{3,})", path.stem, re.I)
    return match.group(1).upper() if match else ""


def repeated_edge_lines(pages: list[list[str]]) -> set[str]:
    if len(pages) < 2:
        return set()
    """Find short lines recurring at page tops/bottoms (running headers/footers)."""
    candidates: list[str] = []
    for lines in pages:
        nonempty = [line for line in lines if line]
        candidates.extend(set(nonempty[:2] + nonempty[-2:]))
    threshold = max(3, round(len(pages) * 0.45))
    counts = Counter(line for line in candidates if 3 <= len(line) <= 90)
    return {line for line, count in counts.items() if count >= threshold}


def is_heading(line: str) -> tuple[int, str] | None:
    compact = line.strip().strip("#").strip()
    if len(compact) > 55:
        return None
    if compact in {"摘要", "关键词", "参考文献", "致谢", "附录"}:
        return 2, compact
    if any(pattern.match(compact) for pattern in H3_PATTERNS):
        return 3, compact
    if any(pattern.match(compact) for pattern in H2_PATTERNS):
        return 2, compact
    return None


def should_join(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if is_heading(right) or PAGE_NUMBER_RE.match(right):
        return False
    if left.endswith(("。", "！", "？", "；", ":", "：", ".", "!", "?", ";")):
        return False
    if left.endswith("-") and re.match(r"^[A-Za-z]", right):
        return True
    # Chinese academic PDF line wraps normally have no punctuation at the break.
    if re.search(r"[\u3400-\u9fff，、（(《“]$", left):
        return True
    if re.match(r"^[\u3400-\u9fffA-Za-z0-9（(《“]", right):
        return True
    return False


def clean_page_lines(raw_text: str, repeated: set[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in raw_text.splitlines():
        line = normalize_text(raw)
        if not line or line in repeated or PAGE_NUMBER_RE.match(line):
            continue
        cleaned.append(line)
    return cleaned


def lines_to_markdown(lines: list[str]) -> str:
    blocks: list[str] = []
    paragraph = ""

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(paragraph.strip())
            paragraph = ""

    for line in lines:
        heading = is_heading(line)
        if heading:
            flush()
            level, text = heading
            blocks.append(f"{'#' * level} {text}")
            continue

        if re.match(r"^(?:摘要|【摘要】|摘\s*要)[:：]?", line):
            flush()
            body = re.sub(r"^(?:摘要|【摘要】|摘\s*要)[:：]?\s*", "", line)
            blocks.append("## 摘要")
            paragraph = body
            continue
        if re.match(r"^(?:关键词|【关键词】|关键字)[:：]?", line):
            flush()
            body = re.sub(r"^(?:关键词|【关键词】|关键字)[:：]?\s*", "", line)
            blocks.extend(["## 关键词", body])
            continue

        if re.match(r"^\[?\d+\]?\s*[.、]", line) and blocks and any(
            block == "## 参考文献" for block in blocks[-3:]
        ):
            flush()
            blocks.append(f"- {line}")
            continue

        if paragraph and should_join(paragraph, line):
            if paragraph.endswith("-") and re.match(r"^[A-Za-z]", line):
                paragraph = paragraph[:-1] + line
            else:
                paragraph += (" " if re.search(r"[A-Za-z0-9]$", paragraph) and re.match(r"^[A-Za-z0-9]", line) else "") + line
        else:
            flush()
            paragraph = line
    flush()

    text = "\n\n".join(block for block in blocks if block.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def convert_pdf(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    metadata: dict[str, dict[str, str]],
    overwrite: bool,
    page_markers: bool,
    min_chars_per_page: int,
    paper_id: str = "",
    source_name: str = "",
) -> Result:
    relative = pdf_path.relative_to(input_root) if input_root.is_dir() else Path(pdf_path.name)
    output_path = output_root / f"{paper_id}.md" if paper_id else (output_root / relative).with_suffix(".md")
    if output_path.exists() and not overwrite:
        return Result(str(pdf_path), str(output_path), "跳过（已存在）")

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            raw_pages = [normalize_text(page.extract_text(x_tolerance=2, y_tolerance=3) or "") for page in pdf.pages]
            page_count = len(pdf.pages)
        page_lines = [[normalize_text(line) for line in text.splitlines() if normalize_text(line)] for text in raw_pages]
        repeated = repeated_edge_lines(page_lines)
        cleaned_pages = [clean_page_lines(text, repeated) for text in raw_pages]
        bodies = [lines_to_markdown(lines) for lines in cleaned_pages]
        char_count = sum(len(re.sub(r"\s+", "", body)) for body in bodies)
        if not char_count:
            raise ValueError("PDF 没有可提取文字，需先进行 OCR；未生成可用 Markdown")

        sid = paper_id or sample_id(pdf_path)
        meta = metadata.get(sid, {})
        title = (meta.get("title") or re.sub(r"^P\d{3,}_?", "", pdf_path.stem)).strip()
        authors = (meta.get("authors") or "").strip()
        doi = (meta.get("doi") or "").strip()
        journal = (meta.get("journal") or "").strip()
        warnings: list[str] = []
        if page_count and char_count / page_count < min_chars_per_page:
            warnings.append("文本量偏低，可能是扫描件、图片页或字体编码异常，建议OCR复核")
        if not any("摘要" in page for page in bodies[:2]):
            warnings.append("未识别到摘要标题")

        frontmatter = [
            "---",
            f"title: {yaml_quote(title)}",
            f"sample_id: {yaml_quote(sid)}",
            f"source_pdf: {yaml_quote(source_name or pdf_path.name)}",
            f"pages: {page_count}",
            f"characters: {char_count}",
            "extraction_method: pdfplumber-text-layer",
            f"converted_at: {yaml_quote(datetime.now().astimezone().isoformat(timespec='seconds'))}",
        ]
        if authors:
            frontmatter.append(f"authors: {yaml_quote(authors)}")
        if journal:
            frontmatter.append(f"journal: {yaml_quote(journal)}")
        if doi:
            frontmatter.append(f"doi: {yaml_quote(doi)}")
        if warnings:
            frontmatter.append(f"warnings: {yaml_quote('；'.join(warnings))}")
        frontmatter.append("---")

        content: list[str] = ["\n".join(frontmatter), f"# {title}"]
        if authors:
            content.append(f"**作者：** {authors}")
        if journal or doi:
            source_bits = [bit for bit in (journal, f"DOI: {doi}" if doi else "") if bit]
            content.append("**来源：** " + "；".join(source_bits))
        for index, body in enumerate(bodies, start=1):
            if not body:
                continue
            if page_markers:
                content.append(f"<!-- PDF page {index} -->")
            content.append(body)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n\n".join(content).strip() + "\n", encoding="utf-8")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise OSError("Markdown 写入后校验失败")

        return Result(
            str(pdf_path), str(output_path), "成功", page_count, char_count, "；".join(warnings)
        )
    except Exception as exc:  # keep a batch moving if one file is malformed
        return Result(str(pdf_path), str(output_path), "失败", error=f"{type(exc).__name__}: {exc}")


def find_pdfs(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError("输入文件不是 PDF")
        return [input_path]
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(input_path.glob(pattern), key=lambda path: path.name.casefold())


def write_report(results: list[Result], output_root: Path) -> Path:
    report_path = output_root / "conversion_report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将文本型 PDF 批量转换为信息优先的 Markdown")
    parser.add_argument("input", type=Path, help="PDF 文件或包含 PDF 的目录")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Markdown 输出目录")
    parser.add_argument("--metadata", type=Path, help="可选：含 sample_id/title/authors/doi/journal 的 CSV")
    parser.add_argument("--recursive", action="store_true", help="递归查找子目录")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的 Markdown")
    parser.add_argument("--no-page-markers", action="store_true", help="不写入 PDF 页码注释")
    parser.add_argument("--workers", type=int, default=4, help="并行任务数，默认 4")
    parser.add_argument("--min-chars-per-page", type=int, default=80, help="低文本量告警阈值")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    output_root = args.output.resolve()
    if not input_path.exists():
        print(f"输入不存在：{input_path}", file=sys.stderr)
        return 2
    pdfs = find_pdfs(input_path, args.recursive)
    if not pdfs:
        print("未找到 PDF 文件", file=sys.stderr)
        return 2
    input_root = input_path if input_path.is_dir() else input_path.parent
    metadata = metadata_map(args.metadata.resolve() if args.metadata else None)

    results: list[Result] = []
    workers = max(1, min(args.workers, 16))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                convert_pdf,
                pdf,
                input_root,
                output_root,
                metadata,
                args.overwrite,
                not args.no_page_markers,
                args.min_chars_per_page,
            ): pdf
            for pdf in pdfs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(f"[{completed:>3}/{len(pdfs)}] {result.status}: {Path(result.source).name}")

    results.sort(key=lambda result: Path(result.source).name.casefold())
    report = write_report(results, output_root)
    successes = sum(result.status == "成功" for result in results)
    failures = sum(result.status == "失败" for result in results)
    warnings = sum(bool(result.warnings) for result in results)
    print(f"完成：成功 {successes}，失败 {failures}，含告警 {warnings}")
    print(f"转换报告：{report}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

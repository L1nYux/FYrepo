"""在独立进程中转换一份真实 PDF，供常驻 worker 调用。"""
import json
import sys
from dataclasses import asdict
from pathlib import Path
from .pdf_to_md import convert_pdf


def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    pdf = Path(spec['pdf'])
    result = convert_pdf(pdf, pdf.parent, Path(spec['output']),
                         {spec['paper_id']: spec['metadata']}, True, True, 80,
                         paper_id=spec['paper_id'], source_name=spec['source_name'])
    Path(spec['result']).write_text(json.dumps(asdict(result), ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()

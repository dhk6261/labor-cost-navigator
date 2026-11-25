"""외부 라이브러리 없이 한글 텍스트 PDF(한 쪽)를 만든다. 시연용 가상 파일 생성 전용.

글꼴은 내장하지 않고 PDF 표준 한글 CID 글꼴(HYGoThic-Medium, UniKS-UCS2-H)을 지정한다.
텍스트 추출이 되도록 /ToUnicode(UCS2 → 유니코드 동일 대응) 표를 함께 넣는다.
"""
from __future__ import annotations

from pathlib import Path

TO_UNICODE = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfrange
<0000> <FFFF> <0000>
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end"""


def _hex(text: str) -> str:
    return "<" + text.encode("utf-16-be").hex().upper() + ">"


def write_pdf(path: Path, lines: list[str], size: int = 10, leading: int = 16) -> None:
    ops = [f"BT /F1 {size} Tf {leading} TL 50 800 Td"]
    for i, line in enumerate(lines):
        ops.append(("" if i == 0 else "T* ") + f"{_hex(line)} Tj")
    ops.append("ET")
    content = "\n".join(ops).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /HYGoThic-Medium /Encoding /UniKS-UCS2-H /DescendantFonts [6 0 R] /ToUnicode 7 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /HYGoThic-Medium /CIDSystemInfo << /Registry (Adobe) /Ordering (Korea1) /Supplement 1 >> /FontDescriptor 8 0 R /DW 1000 >>",
        b"<< /Length %d >>\nstream\n" % len(TO_UNICODE) + TO_UNICODE + b"\nendstream",
        b"<< /Type /FontDescriptor /FontName /HYGoThic-Medium /Flags 6 /FontBBox [-6 -145 1003 880] /ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 880 /StemV 93 >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info << /Title (Demo) >> >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    Path(path).write_bytes(bytes(out))

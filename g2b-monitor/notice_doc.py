"""입찰 공고서(첨부파일)를 내려받아 본문 글자를 꺼내고, 소기업·소상공인 제한 문구를 찾는다.

지원 형식: .hwpx(표준 라이브러리), .hwp(olefile 필요), .pdf(pypdf 필요), .docx, .txt
라이브러리가 없거나 읽을 수 없는 파일이면 None 을 돌려준다 (호출한 쪽은 '공고서 확인 못함'으로 처리).
"""
from __future__ import annotations

import io
import re
import struct
import urllib.request
import zipfile
import zlib

MAX_BYTES = 15 * 1024 * 1024
UA = "Mozilla/5.0 (X11; Linux x86_64) g2b-monitor"


def download(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.g2b.go.kr/"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read(MAX_BYTES + 1)
    except Exception:
        return None
    return None if len(data) > MAX_BYTES else data


# ── 형식별 글자 꺼내기 ───────────────────────────────────────────────

def _xml_text(xml: bytes) -> str:
    return re.sub(r"<[^>]+>", " ", xml.decode("utf-8", "replace"))


def text_hwpx(data: bytes) -> str | None:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    parts = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n))
    return " ".join(_xml_text(z.read(n)) for n in parts) or None


def text_docx(data: bytes) -> str | None:
    try:
        return _xml_text(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
    except Exception:
        return None


def _hwp_para_text(raw: bytes) -> str:
    """HWP5 PARA_TEXT 레코드(UTF-16LE)에서 제어문자를 건너뛰고 글자만."""
    out, i, n = [], 0, len(raw) // 2
    while i < n:
        c = struct.unpack_from("<H", raw, i * 2)[0]
        if c < 32:
            if c in (10, 13):
                out.append("\n")
            # 1~9, 11~12, 14~23 은 8글자(16바이트) 길이의 인라인/확장 제어문자
            i += 8 if (1 <= c <= 9 or c in (11, 12) or 14 <= c <= 23) else 1
            continue
        out.append(chr(c))
        i += 1
    return "".join(out)


def text_hwp(data: bytes) -> str | None:
    try:
        import olefile  # type: ignore
    except ImportError:
        return None
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        compressed, encrypted, distributed = flags & 1, flags & 2, flags & 4
        if encrypted or distributed:  # 암호·배포용 문서는 본문을 읽을 수 없음
            return None
        sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"),
                          key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
        texts = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            pos = 0
            while pos + 4 <= len(raw):
                hdr = struct.unpack_from("<I", raw, pos)[0]
                tag, size = hdr & 0x3FF, (hdr >> 20) & 0xFFF
                pos += 4
                if size == 0xFFF:
                    size = struct.unpack_from("<I", raw, pos)[0]
                    pos += 4
                if tag == 67:  # HWPTAG_PARA_TEXT
                    texts.append(_hwp_para_text(raw[pos:pos + size]))
                pos += size
        return "\n".join(texts) or None
    except Exception:
        return None


def text_pdf(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:30]) or None
    except Exception:
        return None


def extract_text(name: str, data: bytes) -> str | None:
    low = name.lower()
    if low.endswith(".hwpx"):
        return text_hwpx(data)
    if low.endswith(".hwp"):
        return text_hwp(data) or text_hwpx(data)  # 확장자만 hwp 인 hwpx 도 있음
    if low.endswith(".pdf"):
        return text_pdf(data)
    if low.endswith(".docx"):
        return text_docx(data)
    if low.endswith(".txt"):
        return data.decode("utf-8", "replace")
    return None


# ── 소기업·소상공인 제한 찾기 ────────────────────────────────────────

# 예) "소기업·소상공인으로 제한", "소기업 및 소상공인에 한함", "소기업·소상공인 확인서를 소지한 업체로 제한",
#     "소상공인만 참가", "소기업·소상공인 제한경쟁"
_PATTERN = re.compile(
    r"(?:소기업(?:및|또는|과|와)?소상공인|소상공인)"
    r"(?:확인서(?:를|을)?(?:소지|보유|발급받)[가-힣]{0,4}?(?:업체|자|사업자)?)?"
    r"(?:으로|로|에|에게|과의|만|인업체로|인자로|인자에)?"
    r"(?:제한|한정|한함|한하여|한한|만참가|만입찰|만투찰|참가가능)"
)
# 제한이 아니라 가점·우대 얘기이거나, 제한하지 않는다는 문장은 제외
_NOT_LIMIT = re.compile(r"(제한하지|제한없|제한을두지|해당없|미적용|적용하지|가점|감점|우대|배점|평가)")


def _norm(text: str) -> str:
    t = re.sub(r"\s+", "", text)
    # 가운뎃점·쉼표·따옴표·괄호는 지워서 문구 모양을 하나로 맞춤
    return re.sub(r"[·ㆍ‧∙・•,‘’'\"“”<>〈〉《》「」『』()\[\]{}]", "", t)


# 예) "소기업 또는 소상공인으로서 <소기업·소상공인 확인서>를 소지한 업체이어야 합니다"
#     "…소상공인으로서 『중소기업·소상공인 및 장애인기업 확인요령』에 따라 발급된 소기업·소상공인 확인서를 소지한 자"
_AS_QUALIFIED = re.compile(r"소상공인(?:으로서|이어야|이여야|에해당하는자)")
_BENEFIT = re.compile(r"(가점|감점|우대|배점|평가|면제|감면|할인|우선구매)")


def small_biz_restriction(text: str) -> str | None:
    """참가자격을 소기업·소상공인으로 제한하는 문구가 있으면 그 부근 글자를 돌려준다."""
    t = _norm(text)
    for m in _PATTERN.finditer(t):
        if _NOT_LIMIT.search(t[m.end() - 4:m.end() + 15]):
            continue
        return t[max(0, m.start() - 10):m.end() + 10]
    for m in _AS_QUALIFIED.finditer(t):
        span = t[m.start():m.end() + 150]
        if m.group().startswith("소상공인이") or "확인서" in span:
            if _BENEFIT.search(span[:120]) or "제한하지" in span[:60]:
                continue  # 확인서 내면 가점·보증금 면제 같은 혜택 얘기
            return t[max(0, m.start() - 15):m.end() + 35]
    return None


def mentions(text: str, limit: int = 3) -> list[str]:
    """'소상공인'이 나오는 부근 글자들 (판정이 맞는지 기록으로 확인하는 용도)."""
    t = _norm(text)
    return [t[max(0, m.start() - 20):m.end() + 25] for m in re.finditer("소상공인", t)][:limit]

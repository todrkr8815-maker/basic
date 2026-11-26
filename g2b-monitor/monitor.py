#!/usr/bin/env python3
"""나라장터 입찰공고 모니터 — 충북(청주 1시간 권역) 축산물·급식 공고.

조달청 나라장터 입찰공고정보서비스(공공데이터포털 OpenAPI)에서
물품·용역 공고를 키워드로 모아, 수요기관 위치로 청주 1시간 권역만 남기고
'새로 올라온 공고'만 알립니다 (지난 실행 이후 게시된 공고, 중복 알림 없음).

  python monitor.py                 # 결과를 화면에 출력 (report.md도 저장)
  python monitor.py --notify        # + 이메일로 알림
  python monitor.py --scheduled     # 정기 실행: 조회 구간을 '전 영업일 7시 ~ 오늘 7시'로 고정
  python monitor.py --mock FILE.xml # API 대신 저장된 응답으로 시험

필요한 환경변수
  G2B_SERVICE_KEY      공공데이터포털 인증키 (Decoding 키 권장, Encoding 키도 자동 처리)
  SMTP_USER, SMTP_PASSWORD   보내는 메일 계정 (기본: 네이버 SMTP, 애플리케이션 비밀번호 권장)
  MAIL_TO                    (선택) 받는 주소. 없으면 SMTP_USER 로 보냄
  SMTP_HOST, SMTP_PORT       (선택) 기본 smtp.naver.com / 465
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

KST = timezone(timedelta(hours=9))
BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
OPS = {
    "물품": "getBidPblancListInfoThngPPSSrch",
    "용역": "getBidPblancListInfoServcPPSSrch",
}
CHUNGBUK_RGN_CD = "43"
HERE = os.path.dirname(os.path.abspath(__file__))
WEEKDAYS = "월화수목금토일"


class ApiError(Exception):
    pass


# ── API ─────────────────────────────────────────────────────────────

def api_get(op: str, params: dict, key: str, mock: str | None = None) -> ET.Element:
    if mock:
        with open(mock, "rb") as f:
            return _parse(f.read())
    url = BASE + op + "?" + urllib.parse.urlencode({"ServiceKey": key, **params})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return _parse(r.read())
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise ApiError(f"HTTP {e.code} ({op}) — 인증키나 활용신청 상태를 확인하세요")
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(3 * (attempt + 1))
    raise ApiError(f"{op} 호출 실패: {last}")


def _parse(body: bytes) -> ET.Element:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise ApiError("XML이 아닌 응답: " + body[:200].decode("utf-8", "replace"))
    if root.tag == "OpenAPI_ServiceResponse":  # 게이트웨이 오류 (키·트래픽 등)
        msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "게이트웨이 오류"
        raise ApiError(msg)
    code = root.findtext(".//resultCode")
    if code not in (None, "00"):
        raise ApiError(f"resultCode={code} {root.findtext('.//resultMsg') or ''}")
    return root


def fetch_all(op: str, params: dict, key: str, mock: str | None) -> list[dict]:
    items, page = [], 1
    while True:
        root = api_get(op, {**params, "numOfRows": 100, "pageNo": page}, key, mock)
        batch = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
        items.extend(batch)
        total = int(root.findtext(".//totalCount") or 0)
        if mock or not batch or len(items) >= total or page >= 30:
            return items
        page += 1


# ── 판정 ────────────────────────────────────────────────────────────

def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=KST)
        except ValueError:
            pass
    return None


def locate(item: dict, rcfg: dict) -> str | None:
    """수요기관 → 공고기관 순으로 이름을 보고 충북 시·군을 찾는다."""
    for field in ("dminsttNm", "ntceInsttNm"):
        name = (item.get(field) or "").replace(" ", "")
        if not name:
            continue
        if name in rcfg["exact_aliases"]:
            return rcfg["exact_aliases"][name]
        for city in rcfg["unique_cities"]:
            if city in name:
                return city
        for alias, city in rcfg["institution_aliases"].items():
            if alias in name:
                return city
        if "충북" in name or "충청북도" in name:
            for area, city in rcfg["ambiguous_areas"].items():
                if area in name:
                    return city
    return None


def looks_chungbuk(item: dict) -> bool:
    text = (item.get("dminsttNm") or "") + (item.get("ntceInsttNm") or "")
    return "충북" in text or "충청북도" in text


def price_of(item: dict) -> tuple[int, str]:
    for field, label in (("presmptPrce", "추정가격"), ("asignBdgtAmt", "배정예산")):
        try:
            v = int(float(item.get(field) or 0))
        except ValueError:
            v = 0
        if v > 0:
            return v, label
    return 0, ""


def won(v: int) -> str:
    if v <= 0:
        return "미공개"
    if v >= 100_000_000:
        return f"{v / 100_000_000:.2f}".rstrip("0").rstrip(".") + "억원"
    if v >= 10_000:
        return f"{round(v / 10_000):,}만원"
    return f"{v:,}원"


def window(now: datetime, anchor_hour: int, scheduled: bool) -> tuple[datetime, datetime]:
    """'새 공고' 조회 구간. 전 영업일 anchor시 ~ 오늘 anchor시 (월요일은 금요일부터).

    정기 실행은 끝을 오늘 anchor시로 고정해, 실행이 조금 늦어져도 날마다 구간이
    빈틈·겹침 없이 이어진다. 수동 실행은 지금까지 본다.
    """
    today = now.replace(hour=anchor_hour, minute=0, second=0, microsecond=0)
    if now < today:
        today -= timedelta(days=1)
    back = {0: 3, 6: 2}.get(today.weekday(), 1)  # 월→금, 일→금
    start = today - timedelta(days=back)
    return start, (today if scheduled else now)


def collect(cfg: dict, key: str, start: datetime, end: datetime, mock: str | None) -> tuple[list[dict], list[str]]:
    bgn, fin = start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M")
    errors: list[str] = []
    found: dict[str, dict] = {}
    streak = 0

    for words in cfg["keywords"].values():
        for word in words:
            for kind, op in OPS.items():
                # 전국 조회(기관 위치로 판정) + 충북 참가제한 조회(위치 못 찾는 공고 보완)
                for rgn in ((None,) if mock else (None, CHUNGBUK_RGN_CD)):
                    params = {"inqryDiv": "1", "inqryBgnDt": bgn, "inqryEndDt": fin, "bidNtceNm": word}
                    if rgn:
                        params["prtcptLmtRgnCd"] = rgn
                    try:
                        rows = fetch_all(op, params, key, mock)
                    except ApiError as e:
                        errors.append(f"{kind}/{word}{'/충북제한' if rgn else ''}: {e}")
                        streak += 1
                        if streak >= 3 or "SERVICE_KEY" in str(e) or "HTTP 4" in str(e):
                            errors.append("연속 실패로 조회를 중단했습니다.")
                            return list(found.values()), errors
                        continue
                    streak = 0
                    for it in rows:
                        no = it.get("bidNtceNo")
                        if not no:
                            continue
                        it["_kind"], it["_rgn43"] = kind, bool(rgn)
                        prev = found.get(no)
                        if prev:  # 같은 공고: 차수 높은(정정) 공고를 남김
                            r43 = prev["_rgn43"] or bool(rgn)
                            if (prev.get("bidNtceOrd") or "") >= (it.get("bidNtceOrd") or ""):
                                prev["_rgn43"] = r43
                                continue
                            it["_rgn43"] = r43
                        found[no] = it
    return list(found.values()), errors


def classify(items: list[dict], cfg: dict, now: datetime, start: datetime, end: datetime) -> dict:
    """구간 안에 게시된 공고 중 권역 안(new)과 충북인데 위치 미상(check)만 남긴다."""
    rcfg = cfg["region"]
    out = {"new": [], "check": []}
    for it in items:
        title = it.get("bidNtceNm") or ""
        if "취소" in (it.get("ntceKindNm") or "") or any(x in title for x in cfg["exclude"]):
            continue
        posted = parse_dt(it.get("bidNtceDt"))
        if posted and not (start <= posted < end + timedelta(minutes=1)):
            continue
        close = parse_dt(it.get("bidClseDt"))
        if close and close < now:
            continue
        city = locate(it, rcfg)
        it["_city"], it["_close"], it["_posted"] = city, close, posted
        if city is None:
            if it["_rgn43"] or looks_chungbuk(it):
                out["check"].append(it)
            continue
        minutes = rcfg["drive_minutes"].get(city, 999)
        if minutes <= rcfg["max_minutes"]:
            it["_min"] = minutes
            out["new"].append(it)
    far = datetime.max.replace(tzinfo=KST)
    for k in out:
        out[k].sort(key=lambda x: x.get("_close") or far)
    return out


# ── 출력 ────────────────────────────────────────────────────────────

def fmt_dt(d: datetime | None) -> str:
    return f"{d:%m/%d}({WEEKDAYS[d.weekday()]}) {d:%H:%M}" if d else "미정"


def dday(d: datetime | None, now: datetime) -> str:
    if not d:
        return ""
    n = (d.date() - now.date()).days
    return "D-day" if n == 0 else f"D-{n}"


def link(it: dict) -> str:
    return it.get("bidNtceDtlUrl") or it.get("bidNtceUrl") or "https://www.g2b.go.kr"


def is_meat(it: dict, cfg: dict) -> bool:
    return any(w in (it.get("bidNtceNm") or "") for w in cfg["keywords"].get("축산", []))


def kind_note(it: dict) -> str:
    k = it.get("ntceKindNm") or ""
    return f" ({k})" if k and k != "등록공고" else ""


def entry(it: dict, now: datetime, cfg: dict) -> list[str]:
    price, label = price_of(it)
    star = " ★축산" if is_meat(it, cfg) else ""
    where = f"{it['_city']}, 약 {it['_min']}분" if "_min" in it else "위치 확인 필요"
    return [
        f"[{it['_kind']}] {it.get('bidNtceNm', '')}{star}{kind_note(it)}",
        f"  기관: {it.get('dminsttNm') or it.get('ntceInsttNm', '')} ({where})",
        f"  게시 {fmt_dt(it['_posted'])} · 마감 {fmt_dt(it['_close'])} {dday(it['_close'], now)}",
        f"  {label or '추정가격'}: {won(price)} · {it.get('cntrctCnclsMthdNm') or '계약방법 미기재'}",
        f"  {link(it)}",
    ]


def render(out: dict, now: datetime, start: datetime, end: datetime, errors: list[str], cfg: dict) -> tuple[str, str]:
    title = f"[나라장터] {now:%m/%d} 청주권 축산·급식 새 공고 {len(out['new'])}건"
    if out["check"]:
        title += f" (+위치확인 {len(out['check'])})"
    lines = [title, f"게시 구간: {fmt_dt(start)} ~ {fmt_dt(end)} · 청주 {cfg['region']['max_minutes']}분 권역", ""]
    for k, head in (("new", "🆕 새 공고"), ("check", "❓ 충북 공고인데 위치 확인 필요")):
        if out[k]:
            lines.append(f"{head} — {len(out[k])}건")
            for it in out[k]:
                lines += entry(it, now, cfg) + [""]
    if not out["new"] and not out["check"]:
        lines.append("새로 올라온 공고가 없습니다.")
    if errors:
        lines += ["", "⚠️ 조회 오류 (이번엔 공고를 놓쳤을 수 있음):"] + [f"  - {e}" for e in errors[:10]]
    return title, "\n".join(lines).rstrip() + "\n"


# ── 이메일 알림 ──────────────────────────────────────────────────────

def build_email(out: dict, now: datetime, start: datetime, end: datetime,
                errors: list[str], cfg: dict, title: str, body: str) -> EmailMessage:
    """새 공고 표가 들어간 HTML 메일 (텍스트 본문도 함께)."""
    def e(x) -> str:
        return html.escape(str(x or ""))

    rows = []
    for k, tag in (("new", "🆕"), ("check", "❓ 위치 확인")):
        for it in out[k]:
            price, label = price_of(it)
            star = ' <b style="color:#c0392b">★축산</b>' if is_meat(it, cfg) else ""
            where = f"{it['_city']} · 약 {it['_min']}분" if "_min" in it else "위치 확인 필요"
            rows.append(
                "<tr>"
                f'<td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">{tag}</td>'
                f'<td style="padding:10px;border-bottom:1px solid #eee">'
                f'<a href="{e(link(it))}" style="font-weight:bold;color:#1a5fb4;text-decoration:none">{e(it.get("bidNtceNm"))}</a>'
                f'{star}{e(kind_note(it))}<br>'
                f'<span style="color:#555">{e(it.get("dminsttNm") or it.get("ntceInsttNm"))} ({e(where)}) · {e(it["_kind"])}</span></td>'
                f'<td style="padding:10px;border-bottom:1px solid #eee;white-space:nowrap">'
                f'{e(fmt_dt(it["_close"]))}<br><b>{e(dday(it["_close"], now))}</b></td>'
                f'<td style="padding:10px;border-bottom:1px solid #eee;white-space:nowrap;text-align:right">'
                f'{e(won(price))}<br><span style="color:#888">{e(label or "추정가격")}</span></td>'
                "</tr>")
    table = ""
    if rows:
        table = ('<table style="border-collapse:collapse;width:100%;font-size:14px">'
                 '<tr style="background:#f5f5f5"><th></th><th style="padding:8px;text-align:left">공고 (누르면 나라장터)</th>'
                 '<th style="padding:8px;text-align:left">마감</th><th style="padding:8px;text-align:right">금액</th></tr>'
                 + "".join(rows) + "</table>")
    warn = ""
    if errors:
        warn = ('<p style="background:#fff3cd;padding:10px">⚠️ 나라장터 조회 중 오류가 나서 이번엔 공고를 놓쳤을 수 있습니다.<br>'
                + "<br>".join(e(x) for x in errors[:5]) + "</p>")
    none = "" if rows else "<p>새로 올라온 공고가 없습니다.</p>"
    page = (f'<div style="font-family:sans-serif;max-width:760px">'
            f'<h2 style="font-size:18px">{e(title)}</h2>'
            f'<p style="color:#666">게시 구간 {e(fmt_dt(start))} ~ {e(fmt_dt(end))} · 청주 {cfg["region"]["max_minutes"]}분 권역 · 물품/용역</p>'
            f'{warn}{table}{none}'
            f'<p style="color:#999;font-size:12px">키워드·권역 설정: g2b-monitor/config.json</p></div>')

    msg = EmailMessage()
    msg["Subject"] = title if not errors else title + " ⚠️조회오류"
    msg.set_content(body)
    msg.add_alternative(page, subtype="html")
    return msg


def send_email(msg: EmailMessage) -> str:
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASSWORD", "").strip()
    if not (user and pw):
        return "이메일: 건너뜀 (SMTP_USER/SMTP_PASSWORD 없음)"
    to = os.environ.get("MAIL_TO", "").strip() or user
    host = os.environ.get("SMTP_HOST", "").strip() or "smtp.naver.com"
    port = int(os.environ.get("SMTP_PORT", "").strip() or 465)
    msg["From"] = user if "@" in user else f"{user}@naver.com"
    msg["To"] = to
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
    return "이메일: 전송"


# ── main ────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--notify", action="store_true", help="이메일로 알림")
    ap.add_argument("--scheduled", action="store_true", help="정기 실행 (구간 끝을 오늘 기준 시각으로 고정)")
    ap.add_argument("--mock", help="API 대신 이 XML 응답 파일 사용 (시험용)")
    ap.add_argument("--now", help="기준 시각 YYYYMMDDHHMM (시험용)")
    ap.add_argument("--out", default="report.md", help="보고서 저장 경로")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    key = os.environ.get("G2B_SERVICE_KEY", "").strip()
    if "%" in key:  # Encoding 키를 넣은 경우 → Decoding 키로 변환
        key = urllib.parse.unquote(key)
    if not key and not args.mock:
        print("G2B_SERVICE_KEY 환경변수가 없습니다. 공공데이터포털 인증키를 넣어 주세요.", file=sys.stderr)
        return 2

    now = parse_dt(args.now) if args.now else datetime.now(KST).replace(second=0, microsecond=0)
    start, end = window(now, cfg.get("anchor_hour", 7), args.scheduled)

    items, errors = collect(cfg, key, start, end, args.mock)
    out = classify(items, cfg, now, start, end)
    title, body = render(out, now, start, end, errors, cfg)

    print(body)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n```text\n{body}```\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## {title}\n\n```text\n{body}```\n")

    hits = len(out["new"]) + len(out["check"])
    if args.notify and (hits or errors or cfg.get("notify_when_empty")):
        try:
            print(send_email(build_email(out, now, start, end, errors, cfg, title, body)), file=sys.stderr)
        except Exception as e:
            print(f"이메일 실패: {e}", file=sys.stderr)
            return 1
    return 1 if errors and not items else 0


if __name__ == "__main__":
    sys.exit(main())

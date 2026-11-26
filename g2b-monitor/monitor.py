#!/usr/bin/env python3
"""나라장터 입찰공고 모니터 — 충북(청주 1시간 권역) 축산물·급식 공고.

조달청 나라장터 입찰공고정보서비스(공공데이터포털 OpenAPI)에서
물품·용역 공고를 키워드로 모아, 수요기관 위치로 청주 1시간 권역만 남기고
마감일·추정가격을 요약해 알립니다.

  python monitor.py                 # 결과를 화면에 출력 (report.md도 저장)
  python monitor.py --notify        # + GitHub 이슈 / 텔레그램으로 알림
  python monitor.py --mock FILE.xml # API 대신 저장된 응답으로 시험

필요한 환경변수
  G2B_SERVICE_KEY      공공데이터포털 인증키 (Decoding 키 권장, Encoding 키도 자동 처리)
  GITHUB_TOKEN, GITHUB_REPOSITORY   (선택) GitHub 이슈로 알림
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (선택) 텔레그램으로 알림
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

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


def collect(cfg: dict, key: str, now: datetime, mock: str | None) -> tuple[list[dict], list[str]]:
    bgn = (now - timedelta(days=cfg["lookback_days"])).strftime("%Y%m%d%H%M")
    end = now.strftime("%Y%m%d%H%M")
    errors: list[str] = []
    found: dict[str, dict] = {}
    streak = 0

    for group, words in cfg["keywords"].items():
        for word in words:
            for kind, op in OPS.items():
                # 전국 조회(기관 위치로 판정) + 충북 참가제한 조회(위치 못 찾는 공고 보완)
                for rgn in ((None,) if mock else (None, CHUNGBUK_RGN_CD)):
                    params = {"inqryDiv": "1", "inqryBgnDt": bgn, "inqryEndDt": end, "bidNtceNm": word}
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
                        it["_kind"], it["_groups"], it["_rgn43"] = kind, {group}, bool(rgn)
                        prev = found.get(no)
                        if prev:  # 같은 공고: 키워드 묶음 합치고, 차수 높은(정정) 공고를 남김
                            groups, r43 = prev["_groups"] | {group}, prev["_rgn43"] or bool(rgn)
                            if (prev.get("bidNtceOrd") or "") >= (it.get("bidNtceOrd") or ""):
                                prev["_groups"], prev["_rgn43"] = groups, r43
                                continue
                            it["_groups"], it["_rgn43"] = groups, r43
                        found[no] = it
    return list(found.values()), errors


def classify(items: list[dict], cfg: dict, now: datetime, new_since: datetime) -> dict:
    rcfg = cfg["region"]
    excl = cfg["exclude"]
    out = {"new": [], "soon": [], "open": [], "check": []}
    soon_limit = now + timedelta(days=cfg["closing_soon_days"])

    for it in items:
        title = it.get("bidNtceNm") or ""
        if "취소" in (it.get("ntceKindNm") or ""):
            continue
        if any(x in title for x in excl):
            continue
        close = parse_dt(it.get("bidClseDt"))
        if close and close < now:
            continue
        city = locate(it, rcfg)
        it["_city"] = city
        it["_close"] = close
        it["_posted"] = parse_dt(it.get("bidNtceDt"))
        if city is None:
            if it["_rgn43"] or looks_chungbuk(it):
                out["check"].append(it)
            continue
        minutes = rcfg["drive_minutes"].get(city, 999)
        if minutes > rcfg["max_minutes"]:
            continue
        it["_min"] = minutes
        if it["_posted"] and it["_posted"] >= new_since:
            out["new"].append(it)
        elif close and close <= soon_limit:
            out["soon"].append(it)
        else:
            out["open"].append(it)

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


def entry(it: dict, now: datetime, meat_words: list[str]) -> list[str]:
    price, label = price_of(it)
    star = " ★축산" if any(w in (it.get("bidNtceNm") or "") for w in meat_words) else ""
    where = it.get("_city")
    where = f"{where}, 약 {it['_min']}분" if where and "_min" in it else (where or "위치 확인 필요")
    no = it.get("bidNtceNo", "")
    ordn = it.get("bidNtceOrd", "")
    kind_note = it.get("ntceKindNm") or ""
    kind_note = f" · {kind_note}" if kind_note and kind_note != "등록공고" else ""
    return [
        f"[{it['_kind']}] {it.get('bidNtceNm', '')}{star}",
        f"  기관: {it.get('dminsttNm') or it.get('ntceInsttNm', '')} ({where})",
        f"  마감: {fmt_dt(it['_close'])} {dday(it['_close'], now)} · 개찰 {fmt_dt(parse_dt(it.get('opengDt')))}",
        f"  {label or '추정가격'}: {won(price)} · {it.get('cntrctCnclsMthdNm') or '계약방법 미기재'}{kind_note}",
        f"  공고번호 {no}-{ordn} · {link(it)}",
    ]


def render(out: dict, now: datetime, errors: list[str], cfg: dict) -> tuple[str, str]:
    total = len(out["new"]) + len(out["soon"]) + len(out["open"])
    title = (f"[나라장터] {now:%Y-%m-%d} 청주권 축산·급식 공고 {total}건"
             f" (신규 {len(out['new'])} · 마감임박 {len(out['soon'])})")
    lines = [title, f"기준: {now:%Y-%m-%d %H:%M} KST · 청주 기준 {cfg['region']['max_minutes']}분 권역 · 물품/용역", ""]
    sections = [
        ("new", "🆕 신규 공고"),
        ("soon", f"⏰ 마감 임박 (D-{cfg['closing_soon_days']} 이내)"),
        ("open", "📋 진행 중"),
        ("check", "❓ 충북 관련이지만 위치 확인 필요"),
    ]
    for k, head in sections:
        if not out[k]:
            continue
        lines.append(f"{head} — {len(out[k])}건")
        for it in out[k]:
            lines += entry(it, now, cfg["keywords"].get("축산", []))
            lines.append("")
    if total == 0 and not out["check"]:
        lines.append("조건에 맞는 진행 중 공고가 없습니다.")
    if errors:
        lines += ["", "⚠️ 조회 오류:"] + [f"  - {e}" for e in errors[:10]]
    return title, "\n".join(lines).rstrip() + "\n"


# ── 알림 ────────────────────────────────────────────────────────────

def http_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def notify_github(title: str, body: str) -> tuple[str, str]:
    """(결과 한 줄, 이슈 주소)."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return "GitHub 이슈: 건너뜀 (GITHUB_TOKEN/GITHUB_REPOSITORY 없음)", ""
    res = http_json(f"https://api.github.com/repos/{repo}/issues",
                    {"title": title, "body": "```text\n" + body + "```"},
                    {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    return "GitHub 이슈: 등록", res.get("html_url", "")


def kakao_messages(out: dict, now: datetime, errors: list[str], cfg: dict, issue_url: str) -> list[tuple[str, str]]:
    """요약 1통 + 신규·마감임박 공고 1건당 1통 (카카오 텍스트 한도 200자)."""
    home = issue_url or "https://www.g2b.go.kr"
    total = len(out["new"]) + len(out["soon"]) + len(out["open"])
    head = (f"[나라장터 {now:%m/%d}] 청주권 축산·급식\n"
            f"진행 중 {total}건 · 🆕신규 {len(out['new'])} · ⏰마감임박 {len(out['soon'])}")
    if out["check"]:
        head += f" · ❓위치확인 {len(out['check'])}"
    if errors:
        head += f"\n⚠️ 조회 오류 {len(errors)}건 — 자세히 보기에서 확인"
    msgs = [(head, home)]
    meat = cfg["keywords"].get("축산", [])
    picks = [("🆕", it) for it in out["new"]] + [("⏰", it) for it in out["soon"]]
    for mark, it in picks[:8]:
        price, label = price_of(it)
        star = "★" if any(w in (it.get("bidNtceNm") or "") for w in meat) else ""
        title = (it.get("bidNtceNm") or "")[:60]
        inst = (it.get("dminsttNm") or it.get("ntceInsttNm") or "")[:30]
        text = (f"{mark}{star} {title}\n"
                f"{inst} ({it.get('_city')})\n"
                f"마감 {fmt_dt(it['_close'])} {dday(it['_close'], now)}\n"
                f"{label or '추정가격'} {won(price)} · {it['_kind']}")
        msgs.append((text, link(it)))
    if len(picks) > 8:
        msgs.append((f"외 {len(picks) - 8}건은 자세히 보기에서 확인하세요.", home))
    return msgs


def notify_telegram(body: str) -> str:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return "텔레그램: 건너뜀 (설정 없음)"
    chunks, cur = [], ""
    for line in body.splitlines(keepends=True):  # 메시지 한도 4096자
        if len(cur) + len(line) > 3800:
            chunks.append(cur)
            cur = ""
        cur += line
    chunks.append(cur)
    for c in chunks:
        http_json(f"https://api.telegram.org/bot{token}/sendMessage",
                  {"chat_id": chat, "text": c, "disable_web_page_preview": True}, {})
    return f"텔레그램: {len(chunks)}개 메시지 전송"


# ── main ────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--notify", action="store_true", help="GitHub 이슈/텔레그램으로 알림")
    ap.add_argument("--mock", help="API 대신 이 XML 응답 파일 사용 (시험용)")
    ap.add_argument("--now", help="기준 시각 YYYYMMDDHHMM (시험용)")
    ap.add_argument("--new-hours", type=int, help="'신규'로 볼 시간 (기본: 월요일 72, 그 외 24)")
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
    hours = args.new_hours or (72 if now.weekday() == 0 else 24)
    new_since = now - timedelta(hours=hours)

    items, errors = collect(cfg, key, now, args.mock)
    out = classify(items, cfg, now, new_since)
    title, body = render(out, now, errors, cfg)

    print(body)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n```text\n{body}```\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## {title}\n\n```text\n{body}```\n")

    hits = len(out["new"]) + len(out["soon"]) + len(out["open"]) + len(out["check"])
    failed_all = bool(errors) and not items
    if args.notify and (hits or errors or cfg.get("notify_when_empty")):
        issue_url = ""
        try:
            msg, issue_url = notify_github(title, body)
            print(msg, file=sys.stderr)
        except Exception as e:  # 알림 하나가 실패해도 다른 채널은 시도
            print(f"GitHub 이슈 실패: {e}", file=sys.stderr)
        if os.environ.get("KAKAO_REFRESH_TOKEN"):
            try:
                import kakao
                print(kakao.send_many(kakao_messages(out, now, errors, cfg, issue_url)), file=sys.stderr)
            except Exception as e:
                print(f"카카오톡 실패: {e}", file=sys.stderr)
        try:
            print(notify_telegram(body), file=sys.stderr)
        except Exception as e:
            print(f"텔레그램 실패: {e}", file=sys.stderr)
    return 1 if failed_all else 0


if __name__ == "__main__":
    sys.exit(main())

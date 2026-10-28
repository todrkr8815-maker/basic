#!/usr/bin/env python3
"""오즈네이쳐 월간 경영 보고서 생성기 (관리회계 기준).

    python3 oznature/report.py 2026-10
    python3 oznature/report.py 2026-09 --data oznature/sample --out oznature/reports/SAMPLE-2026-09.md

표준 라이브러리만 사용합니다. 자료 형식은 oznature/README.md 를 보세요.
금액은 모두 공급가액(부가세 제외) 기준이며, 부가세는 별도 항목에서 다룹니다.
"""

import argparse
import csv
import datetime as dt
import io
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

COGS_TYPES = {"원재료", "상품", "부자재", "외주가공"}  # 매출원가로 보는 매입
ASSET_TYPES = {"자산"}  # 차량·설비 등: 월 손익에서 제외 (감가상각은 결산 때 세무사가 반영)

FILES = {
    "sales": "매출",
    "purchases": "매입",
    "payroll": "인건비",
    "fixed_costs": "고정비",
    "expenses": "기타 경비",
    "inventory": "월말 재고",
    "cash": "자금(잔액·차입금)",
    "products": "품목 기준정보",
    "partners": "거래처 기준정보",
    "budget": "월 목표",
    "annual": "연간 결산(기준점)",
}

# annual.csv 의 항목 이름 (재무제표 과목명 그대로)
BASE_ITEMS = ["매출액", "상품매출", "제품매출", "매출원가", "상품매출원가", "제품매출원가", "매출총이익",
              "판매비와관리비", "제조경비", "감가상각비", "영업이익", "당기순이익", "매출채권", "재고자산", "현금성자산",
              "외상매입금", "차입금", "가지급금"]


# ---------------------------------------------------------------- 읽기·변환

def norm_header(h):
    return re.sub(r"[\s()\[\]/·_\-]", "", h or "")


def read_table(path):
    if not path.exists():
        return None
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"{path}: 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949(엑셀 기본)로 저장해 주세요.")
    rows = csv.DictReader(io.StringIO(text))
    return [{norm_header(k): (v or "").strip() for k, v in r.items() if k} for r in rows]


def parse_date(s):
    m = re.match(r"\s*(\d{4})\D?(\d{1,2})\D?(\d{1,2})", s or "")
    if not m:
        return None
    try:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def parse_month(s):
    m = re.match(r"\s*(\d{4})\D?(\d{1,2})", s or "")
    return (int(m[1]), int(m[2])) if m else None


def parse_num(s):
    s = (s or "").replace(",", "").replace("원", "").replace(" ", "")
    if s in ("", "-"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


def shift(ym, k):
    n = ym[0] * 12 + ym[1] - 1 + k
    return (n // 12, n % 12 + 1)


def month_end(ym):
    y, m = shift(ym, 1)
    return dt.date(y, m, 1) - dt.timedelta(days=1)


def ym_of(d):
    return (d.year, d.month)


def label(ym):
    return f"{ym[0]}년 {ym[1]}월"


# ---------------------------------------------------------------- 표시

def won(x):
    return f"{round(x):,}"


def krw(x):
    if abs(x) >= 1e8:
        return f"{x / 1e8:,.2f}억원"
    if abs(x) >= 1e4:
        return f"{x / 1e4:,.0f}만원"
    return f"{round(x):,}원"


def ratio(a, b):
    return a / b * 100 if b else None


def pct(x):
    return "-" if x is None else f"{x:.1f}%"


def change(cur, prev):
    if not prev:
        return "-"
    c = (cur - prev) / abs(prev) * 100
    return f"{'▲' if c > 0 else '▼' if c < 0 else ''}{abs(c):.1f}%"


def pp(cur, prev):
    if cur is None or prev is None:
        return "-"
    d = cur - prev
    return f"{'▲' if d > 0 else '▼' if d < 0 else ''}{abs(d):.1f}%p"


def table(headers, rows, align=None):
    align = align or ["---"] + ["---:"] * (len(headers) - 1)
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ---------------------------------------------------------------- 장부

class Books:
    """data 폴더의 CSV를 읽어 월별로 계산한다."""

    AMOUNT_COLS = {
        "sales": ["공급가액", "부가세", "수수료", "중량kg"],
        "purchases": ["공급가액", "부가세", "중량kg"],
        "payroll": ["기본급", "수당", "상여", "회사부담4대보험", "퇴직급여"],
        "fixed_costs": ["공급가액", "부가세"],
        "expenses": ["공급가액", "부가세"],
        "inventory": ["중량kg", "금액"],
        "cash": ["잔액", "월상환액"],
        "products": ["표준원가kg", "표준판매가kg"],
        "budget": ["목표금액"],
        "annual": ["금액"],
    }
    DATE_COL = {"sales": "일자", "purchases": "일자", "expenses": "일자",
                "inventory": "기준일", "cash": "기준일"}
    MONTH_COL = {"payroll": "월", "fixed_costs": "월", "budget": "월"}

    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.status = {}
        self.errors = defaultdict(list)
        for key in FILES:
            rows = read_table(self.dir / f"{key}.csv")
            self.status[key] = None if rows is None else len(rows)
            setattr(self, key, self._prepare(key, rows or []))
        self.product_by_code = {p["품목코드"]: p for p in self.products if p.get("품목코드")}
        self.base = defaultdict(dict)
        for r in self.annual:
            if r.get("연도", "").isdigit():
                self.base[int(r["연도"])][norm_header(r.get("항목"))] = r["_금액"]
        self.company = (self.dir / "company.md").read_text("utf-8") if (self.dir / "company.md").exists() else ""

    def _prepare(self, key, rows):
        good = []
        for i, r in enumerate(rows, start=2):  # 2 = 엑셀 행 번호 (머리글 다음)
            bad = []
            for c in self.AMOUNT_COLS.get(key, []):
                v = parse_num(r.get(c, ""))
                if v is None:
                    bad.append(c)
                r["_" + c] = v or 0.0
            if key in self.DATE_COL:
                r["_d"] = parse_date(r.get(self.DATE_COL[key], ""))
                if r["_d"] is None:
                    bad.append(self.DATE_COL[key])
                else:
                    r["_ym"] = ym_of(r["_d"])
            if key in self.MONTH_COL:
                r["_ym"] = parse_month(r.get(self.MONTH_COL[key], ""))
                if r["_ym"] is None:
                    bad.append(self.MONTH_COL[key])
            if bad:
                self.errors[key].append(f"{i}행({', '.join(bad)})")
                continue
            good.append(r)
        return good

    def rows(self, key, ym):
        return [r for r in getattr(self, key) if r.get("_ym") == ym]

    def has_month(self, ym):
        return bool(self.rows("sales", ym))

    def snapshot(self, key, ym):
        """그 달 안에서 가장 늦은 기준일의 행들 (재고·자금)."""
        rows = self.rows(key, ym)
        if not rows:
            return [], None
        last = max(r["_d"] for r in rows)
        return [r for r in rows if r["_d"] == last], last

    def item_key(self, r):
        return r.get("품목코드") or r.get("품목명") or "(품목 미기재)"

    def item_name(self, k):
        p = self.product_by_code.get(k)
        return p["품목명"] if p and p.get("품목명") else k

    # ------------------------------------------------------------ 월 손익

    def month(self, ym):
        M = {"ym": ym}
        s = self.rows("sales", ym)
        M["sales_rows"] = s
        M["revenue"] = sum(r["_공급가액"] for r in s)
        M["returns"] = sum(r["_공급가액"] for r in s if r["_공급가액"] < 0)
        M["fees"] = sum(r["_수수료"] for r in s)
        M["vat_out"] = sum(r["_부가세"] for r in s)
        M["kg_sold"] = sum(r["_중량kg"] for r in s)
        M["taxfree_rev"] = sum(r["_공급가액"] for r in s if r.get("과세구분") == "면세")
        M["rev_goods"] = sum(r["_공급가액"] for r in s if r.get("매출구분") == "상품")
        M["rev_prod"] = sum(r["_공급가액"] for r in s if r.get("매출구분") == "제품")

        p = self.rows("purchases", ym)
        M["purch_rows"] = p
        M["purch_cogs"] = sum(r["_공급가액"] for r in p if r.get("매입구분") in COGS_TYPES)
        M["purch_asset"] = sum(r["_공급가액"] for r in p if r.get("매입구분") in ASSET_TYPES)
        M["purch_other"] = sum(r["_공급가액"] for r in p
                               if r.get("매입구분") not in COGS_TYPES | ASSET_TYPES)
        M["vat_in_direct"] = sum(r["_부가세"] for r in p)
        M["purch_goods"] = sum(r["_공급가액"] for r in p if r.get("매입구분") == "상품")

        pay = self.rows("payroll", ym)
        M["payroll_rows"] = pay
        for r in pay:
            r["_총액"] = sum(r["_" + c] for c in ("기본급", "수당", "상여", "회사부담4대보험", "퇴직급여"))
        M["labor"] = sum(r["_총액"] for r in pay)
        M["headcount"] = len({r.get("직원코드") or i for i, r in enumerate(pay)})

        fx = self.rows("fixed_costs", ym)
        ex = self.rows("expenses", ym)
        M["fixed_rows"], M["exp_rows"] = fx, ex
        M["fixed"] = sum(r["_공급가액"] for r in fx)
        M["other_exp"] = sum(r["_공급가액"] for r in ex) + M["purch_other"]
        M["vat_in_common"] = sum(r["_부가세"] for r in fx + ex)

        # 매출원가: 재고 증감법 > 표준원가 > 매입액 근사 순으로 사용
        open_inv, open_d = self.snapshot("inventory", shift(ym, -1))
        close_inv, close_d = self.snapshot("inventory", ym)
        M["inv_open"] = sum(r["_금액"] for r in open_inv)
        M["inv_close"] = sum(r["_금액"] for r in close_inv)
        M["inv_rows"], M["inv_date"] = close_inv, close_d
        std_ok = s and all(self.product_by_code.get(r.get("품목코드"), {}).get("_표준원가kg") for r in s)
        if open_inv and close_inv:
            M["cogs"] = M["inv_open"] + M["purch_cogs"] - M["inv_close"]
            M["cogs_method"] = f"재고 증감법 (기초재고 {open_d} + 원가성 매입 − 기말재고 {close_d})"
        elif std_ok:
            M["cogs"] = sum(r["_중량kg"] * self.product_by_code[r["품목코드"]]["_표준원가kg"] for r in s)
            M["cogs_method"] = "표준원가법 (판매 중량 × 품목별 표준원가) — 월말 재고 자료가 오면 재고 증감법으로 바뀝니다"
        else:
            M["cogs"] = M["purch_cogs"]
            M["cogs_method"] = "매입액 근사 (그 달 원가성 매입 = 매출원가로 가정) — 재고 증감을 반영하지 못해 오차가 큽니다"

        # 상품(사서 파는 것) / 제품(가공해서 파는 것) 별 이익: 재고에 구분이 있을 때만
        M["split"] = None
        kinds_ok = s and all(r.get("매출구분") in ("상품", "제품") for r in s)
        if open_inv and close_inv and kinds_ok and all(r.get("구분") for r in open_inv + close_inv):
            g_open = sum(r["_금액"] for r in open_inv if r["구분"] == "상품")
            g_close = sum(r["_금액"] for r in close_inv if r["구분"] == "상품")
            cogs_goods = g_open + M["purch_goods"] - g_close
            M["split"] = {"상품": (M["rev_goods"], cogs_goods), "제품": (M["rev_prod"], M["cogs"] - cogs_goods)}

        M["gp"] = M["revenue"] - M["cogs"]
        M["gp_rate"] = ratio(M["gp"], M["revenue"])
        M["sga"] = M["fees"] + M["labor"] + M["fixed"] + M["other_exp"]
        M["op"] = M["gp"] - M["sga"]
        M["op_rate"] = ratio(M["op"], M["revenue"])

        # 손익분기점: 변동비 = 매출원가 + 수수료 + 기타 경비, 고정비 = 인건비 + 고정비
        var = M["cogs"] + M["fees"] + M["other_exp"]
        cm_rate = (M["revenue"] - var) / M["revenue"] if M["revenue"] else 0
        M["fixed_total"] = M["labor"] + M["fixed"]
        M["bep"] = M["fixed_total"] / cm_rate if cm_rate > 0 else None
        M["cm_rate"] = cm_rate * 100

        cash_rows, cash_d = self.snapshot("cash", ym)
        M["cash_date"] = cash_d
        M["cash"] = sum(r["_잔액"] for r in cash_rows if r.get("구분") == "현금성자산")
        M["debt"] = sum(r["_잔액"] for r in cash_rows if r.get("구분") == "차입금")
        M["debt_service"] = sum(r["_월상환액"] for r in cash_rows if r.get("구분") == "차입금")
        M["cash_rows"] = cash_rows

        M["budget"] = {r.get("항목"): r["_목표금액"] for r in self.rows("budget", ym)}
        return M

    # ------------------------------------------------------------ 채권·채무

    def open_items(self, key, ym, paid_col, due_col):
        end = month_end(ym)
        items = []
        for r in getattr(self, key):
            if r["_d"] > end:
                continue
            paid = parse_date(r.get(paid_col, ""))
            if paid and paid <= end:
                continue
            amt = r["_공급가액"] + r["_부가세"]
            if amt <= 0:
                continue
            due = parse_date(r.get(due_col, ""))
            items.append({"who": r.get("거래처") or "(거래처 미기재)", "amt": amt,
                          "age": (end - r["_d"]).days, "overdue": bool(due and due < end)})
        return items


def aging(items):
    b = {"30일 이내": 0, "31~60일": 0, "61~90일": 0, "90일 초과": 0}
    for it in items:
        a = it["age"]
        k = "30일 이내" if a <= 30 else "31~60일" if a <= 60 else "61~90일" if a <= 90 else "90일 초과"
        b[k] += it["amt"]
    return b


def group(rows, key_fn, val_fn):
    g = defaultdict(float)
    for r in rows:
        g[key_fn(r)] += val_fn(r)
    return sorted(g.items(), key=lambda kv: -kv[1])


# ---------------------------------------------------------------- 세무 일정 (법인 기준)

def tax_calendar(ym):
    m = ym[1]
    items = ["10일: 전월분 원천세·지방소득세 신고·납부, 4대보험료 납부",
             "10일: 전월분 전자(세금)계산서 발급 기한 — 늦으면 가산세"]
    extra = {
        1: ["25일: 2기 부가세 확정신고·납부 (7~12월분)"],
        2: ["말일: 2월 급여 지급 시 근로소득 연말정산"],
        3: ["10일: 근로·퇴직소득 지급명세서 제출", "31일: 법인세 신고·납부 (12월 결산 법인)"],
        4: ["25일: 1기 부가세 예정신고·납부 (1~3월분)*", "30일: 법인지방소득세 신고·납부"],
        7: ["25일: 1기 부가세 확정신고·납부 (4~6월분)"],
        8: ["31일: 법인세 중간예납"],
        10: ["25일: 2기 부가세 예정신고·납부 (7~9월분)*"],
    }
    items += extra.get(m, [])
    return items


# ---------------------------------------------------------------- 보고서

def build(books, ym):
    M = books.month(ym)
    P = books.month(shift(ym, -1))
    Y = books.month(shift(ym, -12))
    has_prev = books.has_month(shift(ym, -1))
    has_yoy = books.has_month(shift(ym, -12))
    end = month_end(ym)
    out = []
    w = out.append

    w(f"# (주)오즈네이쳐 월간 경영 보고서 — {label(ym)}")
    w("")
    w(f"> 작성일 {dt.date.today()} · 대상 기간 {ym[0]}-{ym[1]:02d}-01 ~ {end} · 관리회계 기준(부가세 제외)  ")
    w("> 세무 신고용 재무제표가 아닌 **경영 판단용** 수치입니다. 확정 결산은 세무대리인 자료가 기준입니다.")
    w("")

    if not M["sales_rows"]:
        w("## ⚠️ 이번 달 매출 자료가 없습니다")
        w("")
        w(f"`{books.dir.name}/sales.csv` 에 {label(ym)} 매출이 없어 손익을 계산하지 못했습니다. "
          "아래 '자료 점검' 표의 누락 자료를 올려 주시면 바로 다시 작성합니다.")
        w("")
        w(data_quality(books, M, ym))
        return "\n".join(out)

    # ---- 1. 한눈에 보기
    w("## 1. 한눈에 보기")
    w("")
    kpi = [
        ("매출액", krw(M["revenue"]), change(M["revenue"], P["revenue"]) if has_prev else "-",
         change(M["revenue"], Y["revenue"]) if has_yoy else "-"),
        ("매출총이익", f"{krw(M['gp'])} ({pct(M['gp_rate'])})", pp(M["gp_rate"], P["gp_rate"]) if has_prev else "-",
         pp(M["gp_rate"], Y["gp_rate"]) if has_yoy else "-"),
        ("영업이익", f"{krw(M['op'])} ({pct(M['op_rate'])})", change(M["op"], P["op"]) if has_prev else "-",
         change(M["op"], Y["op"]) if has_yoy else "-"),
        ("판매 중량", f"{M['kg_sold']:,.0f}kg", change(M["kg_sold"], P["kg_sold"]) if has_prev else "-",
         change(M["kg_sold"], Y["kg_sold"]) if has_yoy else "-"),
    ]
    if M["cash_date"]:
        kpi.append(("월말 현금성자산", krw(M["cash"]), change(M["cash"], P["cash"]) if P["cash_date"] else "-", "-"))
    w(table(["지표", "이번 달", "전월 대비", "전년 동월 대비"], kpi))
    w("")
    w("이익률 변화는 %p(퍼센트포인트), 금액 변화는 %로 표시했습니다.")
    w("")
    w(baseline(books, M, ym))

    # ---- 2. 경영자 체크포인트
    w("## 2. 경영자 체크포인트")
    w("")
    flags, goods = signals(books, M, P, has_prev, ym)
    for f in flags:
        w(f"- 🔴 {f}")
    for g in goods:
        w(f"- 🟢 {g}")
    if not flags and not goods:
        w("- 특이 신호 없음")
    w("")

    # ---- 3. 손익
    w("## 3. 손익 요약")
    w("")
    rev = M["revenue"]
    pl = [
        ("매출액", won(rev), "100.0%", won(P["revenue"]) if has_prev else "-"),
        ("　(반품·에누리)", won(M["returns"]), pct(ratio(M["returns"], rev)), won(P["returns"]) if has_prev else "-"),
        ("매출원가", won(M["cogs"]), pct(ratio(M["cogs"], rev)), won(P["cogs"]) if has_prev else "-"),
        ("**매출총이익**", f"**{won(M['gp'])}**", f"**{pct(M['gp_rate'])}**", won(P["gp"]) if has_prev else "-"),
        ("판매수수료(플랫폼·PG)", won(M["fees"]), pct(ratio(M["fees"], rev)), won(P["fees"]) if has_prev else "-"),
        ("인건비", won(M["labor"]), pct(ratio(M["labor"], rev)), won(P["labor"]) if has_prev else "-"),
        ("고정비", won(M["fixed"]), pct(ratio(M["fixed"], rev)), won(P["fixed"]) if has_prev else "-"),
        ("기타 경비", won(M["other_exp"]), pct(ratio(M["other_exp"], rev)), won(P["other_exp"]) if has_prev else "-"),
        ("**영업이익**(감가상각 전)", f"**{won(M['op'])}**", f"**{pct(M['op_rate'])}**", won(P["op"]) if has_prev else "-"),
    ]
    w(table(["항목", "이번 달(원)", "매출 대비", "전월(원)"], pl))
    w("")
    if M["split"]:
        w(table(["구분", "매출(원)", "매출원가(원)", "매출총이익(원)", "이익률"],
                [(k, won(r), won(c), won(r - c), pct(ratio(r - c, r))) for k, (r, c) in M["split"].items()]))
        w("")
    w(f"- 매출원가 계산 방식: {M['cogs_method']}")
    if M["purch_asset"]:
        w(f"- 차량·설비 등 자산 매입 {krw(M['purch_asset'])}은 손익에서 제외했습니다 (감가상각은 결산 때 반영).")
    for k, name in (("payroll", "인건비"), ("fixed_costs", "고정비")):
        if not books.rows(k, ym):
            w(f"- {name} 자료가 없어 0원으로 계산했습니다. 영업이익이 실제보다 크게 보일 수 있습니다.")
    if M["budget"]:
        w("")
        rows = []
        for item, actual in (("매출", M["revenue"]), ("매출총이익", M["gp"]), ("영업이익", M["op"])):
            if item in M["budget"]:
                t = M["budget"][item]
                rows.append((item, won(t), won(actual), pct(ratio(actual, t))))
        if rows:
            w("**목표 대비**")
            w("")
            w(table(["항목", "목표(원)", "실적(원)", "달성률"], rows))
    w("")

    # 추이
    trend = []
    for k in range(-5, 1):
        t = shift(ym, k)
        if books.has_month(t):
            T = books.month(t)
            trend.append((f"{t[0] % 100}.{t[1]:02d}", krw(T["revenue"]), pct(T["gp_rate"]), krw(T["op"]), pct(T["op_rate"])))
    if len(trend) > 1:
        w("**최근 추이**")
        w("")
        w(table(["월", "매출", "매출총이익률", "영업이익", "영업이익률"], trend))
        w("")

    # ---- 4. 매출
    w("## 4. 매출 분석")
    w("")
    s = M["sales_rows"]
    ch = group(s, lambda r: r.get("채널") or "(미기재)", lambda r: r["_공급가액"])
    fee_by = dict(group(s, lambda r: r.get("채널") or "(미기재)", lambda r: r["_수수료"]))
    prev_ch = dict(group(P["sales_rows"], lambda r: r.get("채널") or "(미기재)", lambda r: r["_공급가액"]))
    w("**채널별**")
    w("")
    w(table(["채널", "매출(원)", "비중", "수수료율", "전월 대비"],
            [(c, won(v), pct(ratio(v, rev)), pct(ratio(fee_by.get(c, 0), v)),
              change(v, prev_ch.get(c, 0)) if has_prev else "-") for c, v in ch]))
    w("")

    cust = group(s, lambda r: r.get("거래처") or "(미기재)", lambda r: r["_공급가액"])
    active = {c for c, v in cust if v > 0}
    earlier = {r.get("거래처") for r in books.sales if r["_d"] < dt.date(ym[0], ym[1], 1)}
    recent = {r.get("거래처") for r in books.sales
              if shift(ym, -3) <= r["_ym"] <= shift(ym, -1)}
    new, dormant = active - earlier, recent - active
    top5 = sum(v for _, v in cust[:5])
    w(f"**거래처** — 활성 {len(active)}곳 · 신규 {len(new)}곳 · 최근 3개월 거래했으나 이번 달 없음 {len(dormant)}곳 · "
      f"상위 5곳 비중 {pct(ratio(top5, rev))}")
    if not books.has_month(shift(ym, -3)):
        w("(과거 자료가 3개월 미만이라 신규·휴면 수치는 참고만 하세요.)")
    w("")
    w(table(["순위", "거래처", "매출(원)", "비중"],
            [(i + 1, c, won(v), pct(ratio(v, rev))) for i, (c, v) in enumerate(cust[:10])],
            ["---:", "---", "---:", "---:"]))
    if dormant:
        w("")
        w("이번 달 거래가 끊긴 거래처: " + ", ".join(sorted(x for x in dormant if x)[:15])
          + (" 외" if len(dormant) > 15 else ""))
    w("")

    w("**품목별 마진** (상위 15개, 원가는 표준원가 또는 최근 3개월 평균 매입단가)")
    w("")
    w(table(["품목", "판매 중량", "매출(원)", "판매단가/kg", "원가/kg", "마진율"], item_rows(books, M, ym)))
    w("")

    # ---- 5. 매입
    w("## 5. 매입·원가 분석")
    w("")
    p = M["purch_rows"]
    total_p = sum(r["_공급가액"] for r in p)
    w(f"이번 달 매입 합계 {krw(total_p)} (원가성 매입 {krw(M['purch_cogs'])}). "
      f"매출 대비 원가율 {pct(ratio(M['cogs'], rev))}"
      + (f", 전월 {pct(ratio(P['cogs'], P['revenue']))}" if has_prev else "") + ".")
    w("")
    w(table(["매입 구분", "금액(원)", "비중"],
            [(t, won(v), pct(ratio(v, total_p))) for t, v in group(p, lambda r: r.get("매입구분") or "(미기재)", lambda r: r["_공급가액"])]))
    w("")
    vend = group(p, lambda r: r.get("거래처") or "(미기재)", lambda r: r["_공급가액"])
    w("**주요 매입처**")
    w("")
    w(table(["순위", "매입처", "금액(원)", "비중"],
            [(i + 1, v, won(a), pct(ratio(a, total_p))) for i, (v, a) in enumerate(vend[:10])],
            ["---:", "---", "---:", "---:"]))
    w("")
    price = price_moves(books, ym)
    if price:
        w("**매입단가 변동** (전월 평균 대비 ±5% 이상)")
        w("")
        w(table(["품목", "전월 원/kg", "이번 달 원/kg", "변동"], price))
        w("")

    # ---- 6. 비용
    w("## 6. 비용 구조")
    w("")
    if M["payroll_rows"]:
        by_job = group(M["payroll_rows"], lambda r: r.get("직무") or r.get("부서") or "(미기재)", lambda r: r["_총액"])
        w(f"**인건비** {krw(M['labor'])} · {M['headcount']}명 · 1인당 {krw(M['labor'] / M['headcount'])} · "
          f"매출 대비 {pct(ratio(M['labor'], rev))}")
        w("")
        w(table(["직무/부서", "금액(원)", "비중"], [(j, won(v), pct(ratio(v, M["labor"]))) for j, v in by_job]))
        w("")
    if M["fixed_rows"]:
        w(f"**고정비** {krw(M['fixed'])}")
        w("")
        w(table(["항목", "금액(원)", "전월(원)"],
                fixed_rows(M["fixed_rows"], P["fixed_rows"], has_prev)))
        w("")
    exp = group(M["exp_rows"], lambda r: r.get("계정과목") or r.get("항목") or "(미기재)", lambda r: r["_공급가액"])
    if M["purch_other"]:
        exp.append(("매입 중 비용성(물류·소모품 등)", M["purch_other"]))
    if exp:
        w(f"**기타 경비** {krw(M['other_exp'])}")
        w("")
        w(table(["계정", "금액(원)", "매출 대비"], [(a, won(v), pct(ratio(v, rev))) for a, v in exp]))
        w("")
    if M["bep"]:
        gap = rev - M["bep"]
        w(f"**손익분기점 매출** {krw(M['bep'])} (공헌이익률 {pct(M['cm_rate'])}, 월 고정비 {krw(M['fixed_total'])}). "
          f"이번 달 매출은 분기점 대비 {'여유 ' + krw(gap) if gap >= 0 else '부족 ' + krw(-gap)}입니다.")
        w("")

    # ---- 7. 자금·채권·채무
    w("## 7. 자금·채권·채무")
    w("")
    if M["cash_date"]:
        burn = M["fixed_total"] + M["debt_service"]
        w(f"- {M['cash_date']} 현금성자산 **{krw(M['cash'])}**, 차입금 {krw(M['debt'])}"
          + (f" (월 상환 {krw(M['debt_service'])})" if M["debt_service"] else ""))
        if burn:
            w(f"- 매출이 끊겨도 인건비·고정비·원리금을 버틸 수 있는 기간: 약 **{M['cash'] / burn:.1f}개월**")
    else:
        w("- 자금 자료(cash.csv)가 없어 현금 잔액을 표시하지 못했습니다.")
    ar = books.open_items("sales", ym, "입금일", "입금예정일")
    ap = books.open_items("purchases", ym, "지급일", "지급예정일")
    ar_total, ap_total = sum(i["amt"] for i in ar), sum(i["amt"] for i in ap)
    w(f"- 월말 미수금 **{krw(ar_total)}** (부가세 포함), 미지급금 {krw(ap_total)}")
    if rev and ar_total:
        w(f"- 매출채권 회수기간 약 {ar_total / (rev + M['vat_out']) * end.day:.0f}일")
    if M["inv_date"] and M["cogs"] > 0:
        w(f"- 월말 재고 {krw(M['inv_close'])}, 재고 보유일수 약 {M['inv_close'] / M['cogs'] * end.day:.0f}일")
    w("")
    if ar:
        ag = aging(ar)
        w("**미수금 연령**")
        w("")
        w(table(["구간", "금액(원)", "비중"], [(k, won(v), pct(ratio(v, ar_total))) for k, v in ag.items()]))
        w("")
        debt = defaultdict(lambda: [0.0, 0])
        for it in ar:
            debt[it["who"]][0] += it["amt"]
            debt[it["who"]][1] = max(debt[it["who"]][1], it["age"])
        top = sorted(debt.items(), key=lambda kv: -kv[1][0])[:10]
        w("**미수금 상위 거래처**")
        w("")
        w(table(["거래처", "미수금(원)", "가장 오래된 건"], [(c, won(a), f"{d}일") for c, (a, d) in top]))
        w("")
    inv_flags = inventory_flags(M, end)
    if inv_flags:
        w("**재고 주의**")
        w("")
        for f in inv_flags:
            w(f"- {f}")
        w("")

    # ---- 8. 부가세·세무
    w("## 8. 부가세·세무 일정")
    w("")
    q0 = (ym[0], (ym[1] - 1) // 3 * 3 + 1)
    qm = [books.month(shift(q0, k)) for k in range(ym[1] - q0[1] + 1)]
    vat_out = sum(x["vat_out"] for x in qm)
    direct = sum(x["vat_in_direct"] for x in qm)
    common = sum(x["vat_in_common"] for x in qm)
    qrev = sum(x["revenue"] for x in qm)
    taxable_share = 1 - sum(x["taxfree_rev"] for x in qm) / qrev if qrev else 1
    est = vat_out - direct - common * taxable_share
    w(f"{ym[0]}년 {q0[1]}~{ym[1]}월 누계 기준 예상 부가세: **{krw(est)}** "
      f"(매출세액 {krw(vat_out)} − 매입세액 {krw(direct)} − 공통매입세액 {krw(common)} × 과세매출 비율 {taxable_share * 100:.0f}%)")
    w("")
    w("- 손질·소분만 한 육류는 **면세**, 양념육 등 가공품은 **과세**입니다. 면세 매출이 섞여 있어 "
      "공통 비용(임차료·차량·통신 등)의 매입세액은 과세매출 비율만큼만 공제되는 것으로 추정했습니다.")
    w("- 면세 원육으로 과세 제품(양념육 등)을 만들면 **의제매입세액공제**(중소 제조업 4/104) 대상일 수 있습니다. "
      "위 추정에는 넣지 않았습니다.")
    w("- 카드·현금영수증 매입세액 공제 여부, 불공제 항목은 세무대리인 확인이 필요합니다.")
    w("")
    nxt = shift(ym, 1)
    w(f"**{label(nxt)} 세무 일정** (법인·12월 결산 가정)")
    w("")
    for t in tax_calendar(nxt):
        w(f"- {t}")
    if nxt[1] in (4, 10):
        w("")
        w("\\* 직전 과세기간 공급가액 1억 5천만원 미만 법인은 예정신고 대신 고지서로 납부합니다.")
    w("")

    w(data_quality(books, M, ym))
    return "\n".join(out)


def baseline(books, M, ym):
    years = [y for y in books.base if y < ym[0]]
    if not years:
        return ""
    y = max(years)
    B = books.base[y]
    rev = B.get("매출액")
    if not rev:
        return ""
    days = month_end(ym).day
    rows = [("매출액", krw(M["revenue"]), f"월평균 {krw(rev / 12)}", change(M["revenue"], rev / 12))]

    # 재무제표는 제조경비를 매출원가에, 감가상각비를 판관비에 넣는다. 월 보고서는 매출원가에
    # 재료·상품만 넣고 감가상각을 빼므로, 작년 수치를 같은 기준으로 맞춘다.
    mfg, dep = B.get("제조경비", 0), B.get("감가상각비", 0)

    def margin(r, c):
        if not B.get(r) or c not in B:
            return None
        return ratio(B[r] - B[c] + (mfg if r == "제품매출" else 0), B[r])

    gp_b = ratio(B["매출총이익"] + mfg, rev) if "매출총이익" in B else None
    rows.append(("매출총이익률", pct(M["gp_rate"]), pct(gp_b), pp(M["gp_rate"], gp_b)))
    if M["split"]:
        for k, (r, c) in M["split"].items():
            b = margin(f"{k}매출", f"{k}매출원가")
            rows.append((f"　{k} 이익률", pct(ratio(r - c, r)), pct(b), pp(ratio(r - c, r), b)))
    if "영업이익" in B:
        op_b = ratio(B["영업이익"] + dep, rev)
        rows.append(("영업이익률(감가상각 전)", pct(M["op_rate"]), pct(op_b), pp(M["op_rate"], op_b)))
    if "판매비와관리비" in B:
        sga_b = (B["판매비와관리비"] + mfg - dep) / 12
        rows.append(("운영비(인건비·고정비·경비·수수료)", krw(M["sga"]), f"월평균 {krw(sga_b)}", change(M["sga"], sga_b)))
    if "매출채권" in B:
        ar = sum(i["amt"] for i in books.open_items("sales", ym, "입금일", "입금예정일"))
        cur = f"{ar / (M['revenue'] + M['vat_out']) * days:.0f}일" if M["revenue"] and ar else "-"
        rows.append(("매출채권 회수기간", cur, f"{B['매출채권'] / rev * 365:.0f}일", ""))
    if "재고자산" in B and B.get("매출원가"):
        cur = f"{M['inv_close'] / M['cogs'] * days:.0f}일" if M["inv_date"] and M["cogs"] > 0 else "-"
        rows.append(("재고 보유일수", cur, f"{B['재고자산'] / B['매출원가'] * 365:.0f}일", ""))
    out = [f"**{y}년 결산 대비** (세무대리인 확정 재무제표 기준)", "",
           table(["지표", "이번 달", f"{y}년", "차이"], rows), ""]
    if mfg or dep:
        out += [f"- {y}년 수치는 이 보고서 기준에 맞춰 조정했습니다: 제조경비({krw(mfg)})는 매출원가에서 운영비로 옮기고, "
                f"감가상각비({krw(dep)})는 뺐습니다.", ""]
    if B.get("가지급금"):
        out += [f"- {y}년 말 가지급금 {krw(B['가지급금'])}: 인정이자가 법인 이익에 더해지고 이자비용 일부가 비용으로 "
                "인정되지 않습니다. 정리 계획을 세무대리인과 확인하세요.", ""]
    return "\n".join(out)


def signals(books, M, P, has_prev, ym):
    flags, goods = [], []
    rev = M["revenue"]
    if has_prev and P["revenue"]:
        c = (rev - P["revenue"]) / P["revenue"] * 100
        if c <= -10:
            flags.append(f"매출이 전월보다 {abs(c):.1f}% 줄었습니다 ({krw(P['revenue'])} → {krw(rev)}).")
        elif c >= 10:
            goods.append(f"매출이 전월보다 {c:.1f}% 늘었습니다.")
    if has_prev and M["gp_rate"] is not None and P["gp_rate"] is not None:
        d = M["gp_rate"] - P["gp_rate"]
        if d <= -2:
            flags.append(f"매출총이익률이 {abs(d):.1f}%p 떨어졌습니다 ({pct(P['gp_rate'])} → {pct(M['gp_rate'])}). 매입단가 상승 또는 할인 판매를 확인하세요.")
        elif d >= 2:
            goods.append(f"매출총이익률이 {d:.1f}%p 올랐습니다.")
    if M["op"] < 0:
        flags.append(f"영업손실 {krw(-M['op'])}입니다.")
    cust = group(M["sales_rows"], lambda r: r.get("거래처") or "(미기재)", lambda r: r["_공급가액"])
    if cust and rev and cust[0][1] / rev >= 0.2:
        flags.append(f"거래처 '{cust[0][0]}' 한 곳이 매출의 {cust[0][1] / rev * 100:.0f}%입니다. 이탈 시 타격이 큽니다.")
    total_p = sum(r["_공급가액"] for r in M["purch_rows"])
    vend = group(M["purch_rows"], lambda r: r.get("거래처") or "(미기재)", lambda r: r["_공급가액"])
    if vend and total_p and vend[0][1] / total_p >= 0.4:
        flags.append(f"매입처 '{vend[0][0]}' 의존도가 {vend[0][1] / total_p * 100:.0f}%입니다. 대체 매입처를 확보해 두세요.")
    ar = books.open_items("sales", ym, "입금일", "입금예정일")
    over90 = sum(i["amt"] for i in ar if i["age"] > 90)
    if over90:
        n = len({i["who"] for i in ar if i["age"] > 90})
        flags.append(f"90일 넘은 미수금 {krw(over90)} ({n}곳). 회수 독촉 또는 거래 조건 재검토가 필요합니다.")
    overdue = sum(i["amt"] for i in ar if i["overdue"])
    if overdue and overdue != over90:
        flags.append(f"입금 예정일이 지난 미수금 {krw(overdue)}.")
    if M["cash_date"]:
        burn = M["fixed_total"] + M["debt_service"]
        if burn and M["cash"] / burn < 3:
            flags.append(f"현금이 고정 지출 {M['cash'] / burn:.1f}개월분뿐입니다.")
    if M["bep"] and rev < M["bep"]:
        flags.append(f"매출이 손익분기점({krw(M['bep'])})에 못 미칩니다.")
    neg = [r for r in item_rows(books, M, ym, raw=True) if r[5] is not None and r[5] < 0]
    if neg:
        flags.append("원가보다 싸게 판 품목: " + ", ".join(r[0] for r in neg[:5]))
    for item, actual in (("매출", rev), ("영업이익", M["op"])):
        t = M["budget"].get(item)
        if t and actual < t * 0.9:
            flags.append(f"{item} 목표 달성률 {actual / t * 100:.0f}%.")
    return flags, goods


def avg_cost(books, code, ym):
    p = books.product_by_code.get(code)
    if p and p.get("_표준원가kg"):
        return p["_표준원가kg"]
    rows = [r for r in books.purchases
            if books.item_key(r) == code and shift(ym, -2) <= r["_ym"] <= ym and r["_중량kg"] > 0]
    kg = sum(r["_중량kg"] for r in rows)
    return sum(r["_공급가액"] for r in rows) / kg if kg else None


def item_rows(books, M, ym, raw=False):
    agg = defaultdict(lambda: [0.0, 0.0])
    for r in M["sales_rows"]:
        a = agg[books.item_key(r)]
        a[0] += r["_중량kg"]
        a[1] += r["_공급가액"]
    out = []
    for code, (kg, amt) in sorted(agg.items(), key=lambda kv: -kv[1][1])[:15]:
        price = amt / kg if kg else None
        cost = avg_cost(books, code, ym)
        margin = (price - cost) / price * 100 if price and cost else None
        out.append([books.item_name(code), kg, amt, price, cost, margin])
    if raw:
        return out
    return [(n, f"{kg:,.0f}kg", won(a), won(p) if p else "-", won(c) if c else "-", pct(m))
            for n, kg, a, p, c, m in out]


def price_moves(books, ym):
    def avg(m):
        g = defaultdict(lambda: [0.0, 0.0])
        for r in books.rows("purchases", m):
            if r["_중량kg"] > 0 and r.get("매입구분") in COGS_TYPES:
                g[books.item_key(r)][0] += r["_공급가액"]
                g[books.item_key(r)][1] += r["_중량kg"]
        return {k: a / kg for k, (a, kg) in g.items() if kg}
    cur, prev = avg(ym), avg(shift(ym, -1))
    rows = []
    for k in cur.keys() & prev.keys():
        c = (cur[k] - prev[k]) / prev[k] * 100
        if abs(c) >= 5:
            rows.append((abs(c), (books.item_name(k), won(prev[k]), won(cur[k]), change(cur[k], prev[k]))))
    return [r for _, r in sorted(rows, reverse=True)[:10]]


def fixed_rows(cur, prev, has_prev):
    g = dict(group(cur, lambda r: r.get("항목") or "(미기재)", lambda r: r["_공급가액"]))
    gp = dict(group(prev, lambda r: r.get("항목") or "(미기재)", lambda r: r["_공급가액"]))
    rows = [(k, won(v), won(gp.get(k, 0)) if has_prev else "-") for k, v in sorted(g.items(), key=lambda kv: -kv[1])]
    for k in gp.keys() - g.keys():
        rows.append((f"{k} (이번 달 없음)", "0", won(gp[k])))
    return rows


def inventory_flags(M, end):
    out = []
    rows = M["inv_rows"]
    soon = [r for r in rows if parse_date(r.get("유통기한", "")) and parse_date(r["유통기한"]) <= end + dt.timedelta(days=30)]
    if soon:
        out.append(f"유통기한 30일 이내 재고 {krw(sum(r['_금액'] for r in soon))} "
                   f"({', '.join(sorted({r.get('품목명', '') for r in soon})[:5])})")
    old = [r for r in rows if parse_date(r.get("입고일", "")) and (end - parse_date(r["입고일"])).days > 180]
    if old:
        out.append(f"입고 180일 넘은 장기 재고 {krw(sum(r['_금액'] for r in old))} — 할인 판매·소진 계획 필요")
    by_wh = group(rows, lambda r: r.get("창고") or "(미기재)", lambda r: r["_금액"])
    if len(by_wh) > 1:
        out.append("창고별 재고: " + ", ".join(f"{w} {krw(v)}" for w, v in by_wh))
    return out


def data_quality(books, M, ym):
    lines = ["## 자료 점검", ""]
    rows = []
    for key, name in FILES.items():
        n = books.status[key]
        if n is None:
            st = "❌ 파일 없음"
        elif n == 0:
            st = "⚠️ 비어 있음"
        elif key in ("products", "partners", "annual"):
            st = f"✅ {n}건"
        elif key in Books.DATE_COL or key in Books.MONTH_COL:
            m = len(books.rows(key, ym))
            st = f"✅ 이번 달 {m}건" if m else "⚠️ 이번 달 자료 없음"
        else:
            st = f"✅ {n}건"
        err = books.errors.get(key)
        rows.append((name, f"`{key}.csv`", st, f"읽지 못한 행 {len(err)}개: {', '.join(err[:5])}" if err else ""))
    lines.append(table(["자료", "파일", "상태", "비고"], rows, ["---", "---", "---", "---"]))
    lines.append("")
    s = M["sales_rows"]
    if s:
        no_cust = sum(1 for r in s if not r.get("거래처"))
        no_kg = sum(1 for r in s if not r["_중량kg"])
        if no_cust:
            lines.append(f"- 거래처가 비어 있는 매출 {no_cust}건")
        if no_kg:
            lines.append(f"- 중량(kg)이 비어 있는 매출 {no_kg}건 — 품목별 단가·마진 계산에서 빠집니다")
    if not books.company:
        lines.append("- `company.md`(회사 기본정보)가 없습니다")
    lines.append("- 5일 보고서는 **잠정치**입니다. 전월분 세금계산서는 10일까지 발급될 수 있어, 10일 이후 자료가 바뀌면 다시 작성합니다.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="오즈네이쳐 월간 경영 보고서")
    ap.add_argument("month", help="보고 대상 월 (예: 2026-10)")
    ap.add_argument("--data", default=str(HERE / "data"))
    ap.add_argument("--out", help="저장할 파일 (기본: oznature/reports/YYYY-MM.md)")
    a = ap.parse_args()
    ym = parse_month(a.month)
    if not ym:
        raise SystemExit("월은 2026-10 형식으로 적어 주세요.")
    md = build(Books(a.data), ym)
    out = Path(a.out) if a.out else HERE / "reports" / f"{ym[0]}-{ym[1]:02d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md + "\n", "utf-8")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()

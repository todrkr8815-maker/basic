#!/usr/bin/env python3
"""홈택스에서 받은 매출·매입 자료를 sales.csv / purchases.csv 로 옮긴다.

    python3 oznature/import_hometax.py 받은파일.zip            # Etxiv.txt + Item.txt 가 든 zip
    python3 oznature/import_hometax.py Etxiv.txt --items Item.txt
    python3 oznature/import_hometax.py 목록.xlsx --data oznature/data
    python3 oznature/import_hometax.py 신용카드매출.xls 판매대행매출.xls --since 2026-07

- 전자(세금)계산서 목록: 건별로 넣는다.
- 신용카드 매출자료(월별)·판매(결제)대행 매출자료(월별·업체별): 월 합계 한 줄씩 넣는다.
  금액은 홈택스 그대로(부가세 포함)이며, 면세 위주라 공급가액으로 본다. .xls 는 xlrd 가 필요하다.

- 우리 회사가 공급자면 매출, 공급받는자면 매입으로 넣는다.
- 세금계산서는 과세, 계산서는 면세로 표시한다.
- 승인번호를 비고에 남겨, 같은 파일을 다시 넣어도 중복으로 들어가지 않는다(10일 이후 재수령 대비).
"""

import argparse
import csv
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

SALES_COLS = ["일자", "거래처", "채널", "매출구분", "품목코드", "품목명", "과세구분", "중량kg", "공급가액", "부가세",
              "수수료", "증빙", "입금예정일", "입금일", "비고"]
PURCH_COLS = ["일자", "거래처", "매입구분", "품목코드", "품목명", "과세구분", "중량kg", "공급가액", "부가세", "증빙",
              "지급예정일", "지급일", "비고"]


def decode(raw):
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit("파일 인코딩을 읽을 수 없습니다.")


def grid(name, raw):
    """파일 내용을 행 목록(문자열 리스트)으로."""
    if name.lower().endswith(".xls"):
        try:
            import xlrd
        except ImportError:
            raise SystemExit(".xls 파일을 읽으려면 xlrd 가 필요합니다: pip install xlrd")
        sh = xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
        return [[cell(v) for v in sh.row_values(r)] for r in range(sh.nrows)]
    if name.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl  # 엑셀일 때만 필요
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        return [["" if c is None else str(c).strip() for c in r] for r in wb.active.iter_rows(values_only=True)]
    text = decode(raw)
    delim = "\t" if "\t" in text else ","
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]


def cell(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


PG_CHANNEL = {"네이버": "스마트스토어(네이버)", "쿠팡": "쿠팡", "롯데": "롯데온", "토스": "토스페이먼츠"}


def month_end_str(ym):
    y, m = int(ym[:4]), int(ym[-2:])
    import calendar
    return f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def read_card_pg(g, since):
    """홈택스 신용카드·판매(결제)대행 월별 매출자료 → 월 합계 매출 행."""
    out = []
    hdr, body = table_after(g, "승인년월", "자료구분")
    if hdr:  # 신용카드 매출자료 (월별)
        for r in body:
            d = dict(zip(hdr, r))
            ym = d.get("승인년월", "")
            if not re.match(r"\d{4}-?\d{2}$", ym) or (since and ym.replace("-", "") < since):
                continue
            out.append({"일자": month_end_str(ym), "거래처": "카드 결제 고객", "채널": "카드단말기",
                        "건수": d.get("건수"), "공급가액": int(num(d.get("매출액계"))),
                        "증빙": "신용카드", "비고": f"승인 CARD-{ym.replace('-', '')}"})
        return out
    hdr, body = table_after(g, "승인년월", "판매(결제)대행업체 상호")
    if hdr:  # 판매(결제)대행 매출자료 (월·업체별). 머리글이 2줄이라 위치로 읽는다
        for r in body:
            if len(r) < 7 or not re.match(r"\d{6}$", r[1]) or (since and r[1] < since):
                continue
            ch = next((v for k, v in PG_CHANNEL.items() if k in r[6]), r[6])
            out.append({"일자": month_end_str(r[1]), "거래처": r[6], "채널": ch, "건수": r[2],
                        "공급가액": int(num(r[3])), "증빙": "판매대행", "비고": f"승인 PG-{r[1]}-{ch}"})
    return out


def table_after(rows, *must):
    """머리글(must 를 모두 포함하는 행) 아래의 표를 (머리글, 행들) 로."""
    for i, r in enumerate(rows):
        if all(m in r for m in must):
            body = [x for x in rows[i + 1:] if any(x)]
            return r, body
    return None, []


def own_biz_no(rows):
    for r in rows[:5]:
        for i, c in enumerate(r):
            if c.replace(" ", "") == "사업자등록번호" and i + 1 < len(r):
                return r[i + 1]
    return None


def num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def load_inputs(paths, items_path):
    files = {}
    for path in paths + ([items_path] if items_path else []):
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    files[Path(n).name] = z.read(n)
        else:
            files[path.name] = path.read_bytes()
    head = items = None
    summaries = []
    for name, raw in files.items():
        g = grid(name, raw)
        if table_after(g, "승인번호", "품목순번")[0]:
            items = g
        elif table_after(g, "작성일자", "승인번호")[0]:
            head = g
        elif table_after(g, "승인년월")[0] or any("승인년월" in r for r in g[:5]):
            summaries.append(g)
    if head is None and not summaries:
        raise SystemExit("홈택스 계산서 목록이나 카드·판매대행 매출자료를 찾지 못했습니다.")
    return head, items, summaries


def read_invoices(head, items, biz_no):
    hdr, body = table_after(head, "작성일자", "승인번호")
    pos = defaultdict(list)
    for i, h in enumerate(hdr):
        pos[h].append(i)

    def col(r, name, k=0):
        idx = pos.get(name, [])
        return r[idx[k]] if len(idx) > k and idx[k] < len(r) else ""

    kind_col = next((h for h in hdr if h.endswith("분류")), None)
    item_map = defaultdict(list)
    if items:
        ih, ib = table_after(items, "승인번호", "품목순번")
        for r in ib:
            d = dict(zip(ih, r))
            item_map[d.get("승인번호", "")].append(d)

    out = []
    for r in body:
        appr = col(r, "승인번호")
        if not appr:
            continue
        kind = col(r, kind_col) if kind_col else ""
        tax = "과세" if "세금" in kind else "면세" if kind else ("과세" if num(col(r, "세액")) else "면세")
        seller_no = col(r, "공급자사업자등록번호")
        is_sale = seller_no == biz_no
        lines = item_map.get(appr) or [{"품목명": col(r, "품목명"), "규격": col(r, "품목규격"),
                                         "수량": col(r, "품목수량"), "공급가액": col(r, "공급가액"),
                                         "세액": col(r, "세액")}]
        for k, it in enumerate(lines):
            spec, qty = it.get("규격", ""), num(it.get("수량"))
            kg = qty if qty and (not spec or "kg" in spec.lower()) else ""
            out.append({
                "sale": is_sale,
                "일자": col(r, "작성일자"),
                "거래처": col(r, "상호", 1 if is_sale else 0),
                "품목명": it.get("품목명", ""),
                "과세구분": tax,
                "중량kg": kg,
                "공급가액": int(num(it.get("공급가액"))),
                "부가세": int(num(it.get("세액"))),
                "증빙": kind or ("세금계산서" if tax == "과세" else "계산서"),
                "비고": f"승인 {appr}-{k + 1}" + (f" 규격 {spec}" if spec else ""),
            })
    return out


def append(path, cols, rows):
    seen = set()
    if path.exists() and path.stat().st_size:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                m = re.search(r"승인 (\S+)", r.get("비고", ""))
                if m:
                    seen.add(m[1])
        mode = "a"
    else:
        mode = "w"
    new = [r for r in rows if re.search(r"승인 (\S+)", r["비고"])[1] not in seen]
    with path.open(mode, encoding="utf-8-sig" if mode == "w" else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if mode == "w":
            w.writeheader()
        w.writerows(new)
    return len(new), len(rows) - len(new)


def main():
    ap = argparse.ArgumentParser(description="홈택스 전자(세금)계산서 목록 가져오기")
    ap.add_argument("files", type=Path, nargs="+")
    ap.add_argument("--items", type=Path, help="품목 파일(Item.txt)을 따로 받은 경우")
    ap.add_argument("--data", type=Path, default=HERE / "data")
    ap.add_argument("--biz", help="우리 회사 사업자등록번호 (파일 첫 줄에 없을 때)")
    ap.add_argument("--since", help="카드·판매대행 자료 중 이 달(YYYY-MM)부터만 넣기")
    a = ap.parse_args()

    head, items, summaries = load_inputs(a.files, a.items)
    inv = []
    if head:
        biz = a.biz or own_biz_no(head)
        if not biz:
            raise SystemExit("우리 회사 사업자등록번호를 찾지 못했습니다. --biz 로 알려 주세요.")
        inv = read_invoices(head, items, biz)

    sales, purch = [], []
    since = (a.since or "").replace("-", "")
    for g in summaries:
        sales += [{**r, "매출구분": "", "과세구분": "", "부가세": 0} for r in read_card_pg(g, since)]
    for r in inv:
        if r["sale"]:
            # 과세(양념육 등)는 가공 제품. 면세는 상품/제품을 품목 기준정보로 나중에 나눈다.
            sales.append({**r, "채널": "B2B", "매출구분": "제품" if r["과세구분"] == "과세" else ""})
        else:
            purch.append({**r, "매입구분": "상품" if r["과세구분"] == "면세" else ""})

    a.data.mkdir(parents=True, exist_ok=True)
    for name, cols, rows in (("sales", SALES_COLS, sales), ("purchases", PURCH_COLS, purch)):
        if rows:
            added, dup = append(a.data / f"{name}.csv", cols, rows)
            total = sum(r["공급가액"] for r in rows)
            print(f"{'매출' if name == 'sales' else '매입'}: {added}줄 추가, 중복 {dup}줄 건너뜀 "
                  f"(공급가액 합계 {total:,}원)")


if __name__ == "__main__":
    main()

"""CSV 검증과 지출·예산 계산. 화면(app.py)과 분리해 숫자만 다룬다."""
import calendar
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

REQUIRED_COLUMNS = ["거래ID", "일자", "카테고리", "사용처", "금액_원"]
BUDGET_COLUMNS = ["월", "예산_원"]
CATEGORIES = ["식비", "교통", "쇼핑", "여가", "기타"]

ENCODING_MESSAGE = "UTF-8 형식이 아닌 파일입니다. 엑셀에서 'CSV UTF-8'로 다시 저장해 주세요."


@dataclass
class ParseResult:
    """status: ok | empty | error. error 일 때 df 는 비어 있다."""
    status: str
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    errors: list = field(default_factory=list)  # [(CSV 줄 번호 또는 None, 이유)]


def _read_rows(raw: bytes):
    """(헤더, [(줄번호, 행)]) 를 돌려준다. UTF-8 이 아니면 UnicodeDecodeError."""
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header, rows = None, []
    for row in reader:
        if header is None:
            header = [c.strip() for c in row]
            continue
        if not any(c.strip() for c in row):
            continue
        rows.append((reader.line_num, row))
    return header, rows


def _parse_amount(text: str):
    """(값, 오류 이유). 쉼표가 든 '8,000' 은 8000 으로 읽는다."""
    s = text.strip().replace(",", "")
    if not s:
        return None, "금액이 비어 있음"
    if re.fullmatch(r"\d+", s):
        return int(s), None
    if re.fullmatch(r"-\d+(\.\d+)?", s):
        return None, f"음수 금액({text.strip()})"
    if re.fullmatch(r"\d+\.\d+", s):
        return None, f"소수 금액({text.strip()})"
    return None, f"금액이 숫자가 아님({text.strip()})"


def _parse_date(text: str):
    s = text.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return None, f"날짜 형식 오류({s or '빈 값'}, YYYY-MM-DD 필요)"
    try:
        return datetime.strptime(s, "%Y-%m-%d").date(), None
    except ValueError:
        return None, f"존재하지 않는 날짜({s})"


def parse_expenses(raw: bytes) -> ParseResult:
    try:
        header, rows = _read_rows(raw)
    except UnicodeDecodeError:
        return ParseResult("error", errors=[(None, ENCODING_MESSAGE)])
    if header is None:
        return ParseResult("empty")
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        return ParseResult("error", errors=[(None, "필수 열 누락: " + ", ".join(missing))])
    if not rows:
        return ParseResult("empty")

    idx = {c: header.index(c) for c in REQUIRED_COLUMNS}
    errors, records, seen = [], [], {}
    for line_no, row in rows:
        if len(row) < len(header):
            errors.append((line_no, f"열 개수가 부족함({len(row)}개, {len(header)}개 필요)"))
            continue
        problems = []
        tx_id = row[idx["거래ID"]].strip()
        if not tx_id:
            problems.append("거래ID가 비어 있음")
        elif tx_id in seen:
            problems.append(f"중복 거래ID({tx_id}, {seen[tx_id]}번 줄과 같음)")
        else:
            seen[tx_id] = line_no
        day, err = _parse_date(row[idx["일자"]])
        if err:
            problems.append(err)
        category = row[idx["카테고리"]].strip()
        if category not in CATEGORIES:
            problems.append(f"허용되지 않은 카테고리({category or '빈 값'})")
        place = row[idx["사용처"]].strip()
        if not place:
            problems.append("사용처가 비어 있음")
        amount, err = _parse_amount(row[idx["금액_원"]])
        if err:
            problems.append(err)
        if problems:
            errors.append((line_no, "; ".join(problems)))
        else:
            records.append({"거래ID": tx_id, "일자": day, "카테고리": category,
                            "사용처": place, "금액_원": amount})
    if errors:
        return ParseResult("error", errors=errors)
    df = pd.DataFrame(records)
    df = df.sort_values("일자", kind="stable").reset_index(drop=True)
    return ParseResult("ok", df=df)


def parse_budget(raw: bytes):
    """(예산 dict {YYYY-MM: 원}, 오류 목록). 오류가 있으면 dict 는 비어 있다."""
    try:
        header, rows = _read_rows(raw)
    except UnicodeDecodeError:
        return {}, [(None, ENCODING_MESSAGE)]
    if header is None:
        return {}, []
    missing = [c for c in BUDGET_COLUMNS if c not in header]
    if missing:
        return {}, [(None, "예산 파일 필수 열 누락: " + ", ".join(missing))]
    mi, bi = header.index("월"), header.index("예산_원")
    budgets, errors, seen = {}, [], {}
    for line_no, row in rows:
        if len(row) < len(header):
            errors.append((line_no, "열 개수가 부족함"))
            continue
        problems = []
        month = row[mi].strip()
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            problems.append(f"월 형식 오류({month or '빈 값'}, YYYY-MM 필요)")
        elif month in seen:
            problems.append(f"월 중복({month}, {seen[month]}번 줄과 같음)")
        else:
            seen[month] = line_no
        value, err = _parse_amount(row[bi])
        if err:
            problems.append("예산 " + err)
        if problems:
            errors.append((line_no, "; ".join(problems)))
        else:
            budgets[month] = value
    if errors:
        return {}, errors
    return budgets, []


def months_of(df: pd.DataFrame) -> list:
    return sorted({d.strftime("%Y-%m") for d in df["일자"]})


def select_range(df: pd.DataFrame, month: str, category: str) -> pd.DataFrame:
    out = df[df["일자"].map(lambda d: d.strftime("%Y-%m") == month)]
    if category != "전체":
        out = out[out["카테고리"] == category]
    return out


def category_totals(sub: pd.DataFrame) -> pd.DataFrame:
    if sub.empty:
        return pd.DataFrame(columns=["카테고리", "금액_원"])
    t = sub.groupby("카테고리", as_index=False)["금액_원"].sum()
    return t.sort_values("금액_원", ascending=False, kind="stable").reset_index(drop=True)


def daily_totals(sub: pd.DataFrame, month: str) -> pd.DataFrame:
    """선택한 달의 모든 날짜를 채우고, 거래 없는 날은 0원."""
    year, mon = int(month[:4]), int(month[5:])
    days = [date(year, mon, d) for d in range(1, calendar.monthrange(year, mon)[1] + 1)]
    sums = sub.groupby("일자")["금액_원"].sum().to_dict() if not sub.empty else {}
    return pd.DataFrame({"일자": days, "금액_원": [int(sums.get(d, 0)) for d in days]})


def monthly_totals(df: pd.DataFrame) -> pd.DataFrame:
    t = df.assign(월=df["일자"].map(lambda d: d.strftime("%Y-%m"))).groupby("월", as_index=False)["금액_원"].sum()
    return t.sort_values("월").reset_index(drop=True)


def format_won(n: int) -> str:
    return f"{n:,}원"


def format_rate(spent: int, budget: int) -> str:
    rate = (Decimal(spent) * 100 / Decimal(budget)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rate}%"


@dataclass
class BudgetStatus:
    registered: bool
    budget: int = 0
    spent: int = 0
    remaining: int = 0  # 음수면 초과
    rate_text: str = ""
    rate_ratio: float = 0.0

    @property
    def over(self) -> bool:
        return self.registered and self.remaining < 0


def budget_status(budgets: dict, df: pd.DataFrame, month: str) -> BudgetStatus:
    """카테고리와 무관하게 그 달 전체 지출로 계산한다."""
    spent = int(select_range(df, month, "전체")["금액_원"].sum())
    if month not in budgets:
        return BudgetStatus(False, spent=spent)
    budget = budgets[month]
    if budget == 0:
        rate_text, ratio = "계산 불가(예산 0원)", 0.0
    else:
        rate_text, ratio = format_rate(spent, budget), spent / budget
    return BudgetStatus(True, budget, spent, budget - spent, rate_text, ratio)

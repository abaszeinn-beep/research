"""Build full, unfiltered prospect workbooks from the accepted store directories.

Master Prospects keeps the column headers the filtered workbook was worked in,
in that order. Directory fields are mapped into those columns. Research columns
are copied from the filtered workbook when that store was already researched,
and left blank otherwise. Source-directory columns whose names are not already
in the worked header are appended after it, then Passes Research Filter.

No page-count cutoff and no Semrush traffic cutoff. Decision Makers use the
filtered workbook's headers and the people already researched for these stores.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

OUT = Path(__file__).resolve().parent / "full"
PROSPECTS = Path("/tmp/prospects")
PARENT = Path(__file__).resolve().parent
BRANCH = "cursor/gulf-prospect-research-473e"
RAW = f"https://github.com/abaszeinn-beep/research/raw/{BRANCH}/markets/prospects/full"

DARK = PatternFill("solid", fgColor="1F2933")
ORANGE = "F97316"
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
HEADER_BORDER = Border(bottom=Side(style="thick", color=ORANGE))
BODY_FONT = Font(name="Calibri", size=10)
LINK_FONT = Font(name="Calibri", size=10, color="0563C1", underline="single")
BAND = PatternFill("solid", fgColor="FFF7ED")
HEADER_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)
BODY_ALIGN = Alignment(vertical="top", wrap_text=True)

# Reject sheets from the same directory workbooks as the accepted masters.
# Included only when the sheet has a reason column and at least one data row.
REJECT_SHEETS = (
    "Excluded",
    "Unverified Candidates",
    "Removed - platform subdomain",
    "StoreLeads gap - rejected",
)

EXPECTED = {
    "Saudi_Arabia_Ecommerce_FULL.xlsx": 3935,
    "Saudi_Arabia_Fashion_FULL.xlsx": 576,
    "UAE_Ecommerce_FULL.xlsx": 4772,
    "UAE_Fashion_FULL.xlsx": 371,
    "Qatar_Ecommerce_FULL.xlsx": 717,
    "Qatar_Fashion_FULL.xlsx": 124,
    "Kuwait_Ecommerce_FULL.xlsx": 502,
    "Kuwait_Fashion_FULL.xlsx": 124,
    "USA_Ecommerce_FULL.xlsx": 26213,
    "USA_Fashion_FULL.xlsx": 6726,
}

MARKETS = [
    {
        "file": "Saudi_Arabia_Ecommerce_FULL.xlsx",
        "master": PROSPECTS / "src_Saudi_Arabia_Ecommerce_Master_Directory.csv",
        "directory": Path("/tmp/m/w_saudi-ecommerce-directory-473e/Saudi_Arabia_Ecommerce_Master_Directory.xlsx"),
        "people": [PROSPECTS / "final_saudi/Saudi_people.csv"],
        "filtered": PARENT / "Saudi_Arabia_Ecommerce_Prospects.xlsx",
    },
    {
        "file": "Saudi_Arabia_Fashion_FULL.xlsx",
        "master": PROSPECTS / "src_Saudi_Arabia_Fashion_Stores.csv",
        "directory": Path("/tmp/m/w_fashion-stores-473e/markets/fashion/Saudi_Arabia_Fashion_Stores.xlsx"),
        "people": [PROSPECTS / "final_saudi/Saudi_people.csv"],
        "filtered": PARENT / "Saudi_Arabia_Fashion_Prospects.xlsx",
    },
    {
        "file": "UAE_Ecommerce_FULL.xlsx",
        "master": PROSPECTS / "src_UAE_Ecommerce_Master_Directory.csv",
        "directory": Path("/tmp/m/w_uae-ecommerce-directory-73c6/markets/uae/UAE_Ecommerce_Master_Directory.xlsx"),
        "people": [PROSPECTS / "final_gulf/UAE_people.csv"],
        "filtered": PARENT / "UAE_Ecommerce_Prospects.xlsx",
    },
    {
        "file": "UAE_Fashion_FULL.xlsx",
        "master": PROSPECTS / "src_UAE_Fashion_Stores.csv",
        "directory": Path("/tmp/m/w_fashion-stores-473e/markets/fashion/UAE_Fashion_Stores.xlsx"),
        "people": [PROSPECTS / "final_gulf/UAE_people.csv"],
        "filtered": PARENT / "UAE_Fashion_Prospects.xlsx",
    },
    {
        "file": "Qatar_Ecommerce_FULL.xlsx",
        "master": PROSPECTS / "src_Qatar_Ecommerce_Master_Directory.csv",
        "directory": Path("/tmp/m/w_qatar-ecommerce-directory-9c58/markets/qatar/Qatar_Ecommerce_Master_Directory.xlsx"),
        "people": [PROSPECTS / "final_gulf/Qatar_people.csv"],
        "filtered": PARENT / "Qatar_Ecommerce_Prospects.xlsx",
    },
    {
        "file": "Qatar_Fashion_FULL.xlsx",
        "master": PROSPECTS / "src_Qatar_Fashion_Stores.csv",
        "directory": Path("/tmp/m/w_fashion-stores-473e/markets/fashion/Qatar_Fashion_Stores.xlsx"),
        "people": [PROSPECTS / "final_gulf/Qatar_people.csv"],
        "filtered": PARENT / "Qatar_Fashion_Prospects.xlsx",
    },
    {
        "file": "Kuwait_Ecommerce_FULL.xlsx",
        "master": PROSPECTS / "src_Kuwait_Ecommerce_Master_Directory.csv",
        "directory": Path("/tmp/m/w_kuwait-ecommerce-directory-f1cc/markets/kuwait/Kuwait_Ecommerce_Master_Directory.xlsx"),
        "people": [PROSPECTS / "final_gulf/Kuwait_people.csv"],
        "filtered": PARENT / "Kuwait_Ecommerce_Prospects.xlsx",
    },
    {
        "file": "Kuwait_Fashion_FULL.xlsx",
        "master": PROSPECTS / "src_Kuwait_Fashion_Stores.csv",
        "directory": Path("/tmp/m/w_fashion-stores-473e/markets/fashion/Kuwait_Fashion_Stores.xlsx"),
        "people": [PROSPECTS / "final_gulf/Kuwait_people.csv"],
        "filtered": PARENT / "Kuwait_Fashion_Prospects.xlsx",
    },
    {
        "file": "USA_Ecommerce_FULL.xlsx",
        "master": PROSPECTS / "src_USA_Ecommerce_Master_Directory.csv",
        "directory": Path("/tmp/m/w_usa-ecommerce-directory-fe40/markets/usa/USA_Ecommerce_Master_Directory.xlsx"),
        "people": [PROSPECTS / f"final_usa/USA_shard{i}_people.csv" for i in range(1, 7)],
        "filtered": PARENT / "USA_Ecommerce_Prospects.xlsx",
    },
    {
        "file": "USA_Fashion_FULL.xlsx",
        "master": PROSPECTS / "src_USA_Fashion_Stores.csv",
        "directory": Path("/tmp/m/w_fashion-stores-473e/markets/fashion/USA_Fashion_Stores.xlsx"),
        "people": [PROSPECTS / f"final_usa/USA_shard{i}_people.csv" for i in range(1, 7)],
        "filtered": PARENT / "USA_Fashion_Prospects.xlsx",
    },
]

FILTER_COLUMN = "Passes Research Filter"


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def url_key(value) -> str:
    """Identity for joining a researched URL onto a directory URL.

    http/https, trailing slash, and a leading www are ignored. The path is kept,
    so distinct locale URLs stay distinct.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    if not text.lower().startswith(("http://", "https://")):
        text = "https://" + text
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return host + path


def page_is_blank(value) -> bool:
    text = "" if value is None else str(value).strip()
    return text == "" or text.lower() == "not found"


def as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and not pd.isna(value):
        return int(value) if value.is_integer() else value
    text = "" if value is None else str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number


def passes_research_filter(count, traffic) -> str:
    """(page count blank or Not found or >= 500) AND (Semrush organic traffic >= 1000)."""
    if page_is_blank(count):
        count_ok = True
    else:
        count_num = as_number(count)
        count_ok = isinstance(count_num, (int, float)) and not isinstance(count_num, bool) and count_num >= 500
    traffic_num = as_number(traffic)
    traffic_ok = isinstance(traffic_num, (int, float)) and not isinstance(traffic_num, bool) and traffic_num >= 1000
    return "Yes" if count_ok and traffic_ok else "No"


def metric_column(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith("organic ")
        or "pages count" in lowered
        or lowered in {"website count", "semrush organic traffic"}
        or ("traffic" in lowered and "semrush" in lowered)
    )


def display_value(column: str, value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if metric_column(column):
            return as_number(value)
        return value
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    if metric_column(column):
        number = as_number(text)
        if number is not None and str(text).strip().replace(",", "").replace(".", "", 1).lstrip("-").isdigit():
            return number
    return text


def is_single_url(value) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://")) and " " not in value and ";" not in value


def clean_header(row) -> list[str]:
    header = []
    for cell in row:
        if cell is None:
            header.append("")
        elif isinstance(cell, str):
            header.append(cell)
        else:
            header.append(str(cell))
    while header and header[-1].strip() == "":
        header.pop()
    if any(name.strip() == "" for name in header):
        raise ValueError(f"blank header cell in {header}")
    return header


def read_sheet(path: Path, sheet: str):
    wb = load_workbook(path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        wb.close()
        raise KeyError(f"{path.name} has no sheet {sheet!r} ({wb.sheetnames})")
    ws = wb[sheet]
    rows = ws.iter_rows(values_only=True)
    header = clean_header(next(rows))
    width = len(header)
    data = []
    for row in rows:
        values = list(row[:width])
        if len(values) < width:
            values.extend([None] * (width - len(values)))
        cleaned = []
        for cell in values:
            if isinstance(cell, str):
                cell = cell.strip()
                cell = cell if cell else None
            elif isinstance(cell, float) and pd.isna(cell):
                cell = None
            cleaned.append(cell)
        if any(cell is not None for cell in cleaned):
            data.append(cleaned)
    wb.close()
    return header, data


def column_index(headers: list[str], *names: str) -> int:
    wanted = {name.lower() for name in names}
    for index, header in enumerate(headers):
        if header.lower() in wanted:
            return index
    raise KeyError(names)


def match_source(worked_name: str, source_columns: list[str]):
    """Directory column that can fill a worked header. Research headers return None."""
    by_lower = {column.lower(): column for column in source_columns}
    lower = worked_name.strip().lower()
    if lower in by_lower:
        return by_lower[lower]
    if lower in {"website name", "store name"}:
        return by_lower.get("store name") or by_lower.get("website name")
    if lower in {"root domain link", "website link", "website"}:
        for candidate in ("root domain / storefront url", "website", "root domain link", "website link"):
            if candidate in by_lower:
                return by_lower[candidate]
        return None
    if "organic" in lower and "traffic" in lower:
        for column in source_columns:
            if "organic" in column.lower() and "traffic" in column.lower():
                return column
        return None
    if lower in {"website count", "website pages count"} or "pages count" in lower:
        for column in source_columns:
            cl = column.lower()
            if "pages count" in cl or cl == "website count":
                return column
        return None
    if "country" in lower:
        for column in source_columns:
            if "country" in column.lower():
                return column
        return None
    return None


def read_master(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    before = len(frame)
    frame = frame.drop_duplicates(keep="first")
    dropped = before - len(frame)
    if dropped:
        print(f"  exact duplicate rows dropped from {path.name}: {dropped}")
    return frame


def read_people(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig") for path in paths]
    people = pd.concat(frames, ignore_index=True)
    before = len(people)
    people = people.drop_duplicates(keep="first")
    if len(people) != before:
        print(f"  exact duplicate people rows dropped: {before - len(people)}")
    return people


def read_reject_sheet(path: Path, sheet: str):
    wb = load_workbook(path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        wb.close()
        return None
    ws = wb[sheet]
    rows = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration:
        wb.close()
        return None
    header = ["" if cell is None else str(cell).strip() for cell in header_row]
    while header and header[-1] == "":
        header.pop()
    if not header or not any("reason" in name.lower() for name in header):
        wb.close()
        return None
    data = []
    width = len(header)
    for row in rows:
        values = list(row[:width])
        if any(cell is not None and str(cell).strip() for cell in values):
            data.append(values)
    wb.close()
    if not data:
        return None
    return header, data


def load_excluded(path: Path):
    blocks = []
    for sheet in REJECT_SHEETS:
        found = read_reject_sheet(path, sheet)
        if found:
            blocks.append((sheet, found[0], found[1]))
    if not blocks:
        return [], []
    columns = ["Exclusion list"]
    seen = set(columns)
    for _, header, _ in blocks:
        for name in header:
            if name not in seen:
                columns.append(name)
                seen.add(name)
    rows = []
    for sheet, header, data in blocks:
        index = {name: pos for pos, name in enumerate(header)}
        for values in data:
            record = [None] * len(columns)
            record[0] = sheet
            for name, pos in index.items():
                cell = values[pos] if pos < len(values) else None
                if isinstance(cell, str):
                    cell = cell.strip() or None
                record[columns.index(name)] = cell
            rows.append(record)
    return columns, rows


def style_sheet(ws: Worksheet, widths: list[int], numeric_cols: set[int], full_body: bool):
    for index, width in enumerate(widths, 1):
        cell = ws.cell(row=1, column=index)
        cell.fill = DARK
        cell.font = HEADER_FONT
        cell.border = HEADER_BORDER
        cell.alignment = HEADER_ALIGN
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = "A2"
    last_col = get_column_letter(len(widths))
    ws.auto_filter.ref = f"A1:{last_col}{ws.max_row}"
    ws.sheet_properties.tabColor = ORANGE
    if ws.max_row < 2:
        return
    ws.conditional_formatting.add(
        f"A2:{last_col}{ws.max_row}",
        FormulaRule(formula=["MOD(ROW(),2)=1"], fill=BAND),
    )
    if full_body:
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(widths)):
            for cell in row:
                cell.font = BODY_FONT
                cell.alignment = BODY_ALIGN
                if cell.column in numeric_cols and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                    cell.number_format = "#,##0"
                elif is_single_url(cell.value):
                    cell.hyperlink = cell.value
                    cell.font = LINK_FONT
        return
    # Large reject lists keep header styling, filters, and links without a per-cell body pass.
    for column in range(1, len(widths) + 1):
        letter = get_column_letter(column)
        for cell in ws[letter][1:]:
            if column in numeric_cols and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                cell.number_format = "#,##0"
            elif is_single_url(cell.value):
                cell.hyperlink = cell.value
                cell.font = LINK_FONT


def column_width(name: str) -> int:
    lowered = name.lower()
    if "url" in lowered or "website" in lowered or "link" in lowered or "source" in lowered:
        return 42
    if "reason" in lowered or "position" in lowered or "method" in lowered or "note" in lowered:
        return 36
    return min(max(len(name) + 3, 16), 34)


def write_rows(ws: Worksheet, columns: list[str], rows: list[list], full_body: bool = True):
    ws.append(columns)
    for row in rows:
        ws.append(row)
    numeric = set()
    for index, column in enumerate(columns, 1):
        if metric_column(column) or "score" in column.lower() or column.lower().endswith("rank"):
            numeric.add(index)
    style_sheet(ws, [column_width(name) for name in columns], numeric, full_body=full_body)


def person_identity(header: list[str], row: list, key: str) -> tuple:
    """Same store, same person, and same contact fields count as one researched row."""

    def value(name: str) -> str:
        index = column_index(header, name)
        cell = row[index]
        return "" if cell is None else str(cell).strip().lower()

    return (
        key,
        value("Contact Name"),
        value("Position"),
        value("Email"),
        value("Phone Numbers"),
        value("LinkedIn Profile"),
    )


def build_people_rows(spec, directory_keys: dict[str, int], dm_header: list[str], dm_rows: list[list]):
    """Filtered Decision Makers rows first, then researched people not already on that sheet."""
    link_index = column_index(dm_header, "Website Link", "Root Domain Link", "Website")
    kept = []
    seen = set()
    skipped = 0
    for values in dm_rows:
        key = url_key(values[link_index])
        if key not in directory_keys:
            skipped += 1
            continue
        identity = person_identity(dm_header, values, key)
        if identity in seen:
            continue
        seen.add(identity)
        kept.append((directory_keys[key], len(kept), list(values)))

    people = read_people(spec["people"])
    people_cols = list(people.columns)
    link_col = "Website Link" if "Website Link" in people_cols else people_cols[column_index(people_cols, "Website Link", "Website")]
    added = 0
    for record in people.itertuples(index=False, name=None):
        raw = dict(zip(people_cols, record))
        key = url_key(raw.get(link_col))
        if key not in directory_keys:
            continue
        projected = []
        for column in dm_header:
            if column in raw:
                projected.append(display_value(column, raw[column]))
            else:
                projected.append(None)
        identity = person_identity(dm_header, projected, key)
        if identity in seen:
            continue
        seen.add(identity)
        kept.append((directory_keys[key], len(kept), projected))
        added += 1
    kept.sort(key=lambda item: (item[0], item[1]))
    print(f"  decision makers {len(kept)} (filtered sheet {len(dm_rows) - skipped}, extra researched {added}, skipped not in directory {skipped})")
    return [item[2] for item in kept], skipped


def build_one(spec: dict) -> dict:
    print(f"\n{spec['file']}")
    worked_header, filtered_rows = read_sheet(spec["filtered"], "Master Prospects")
    dm_header, dm_rows = read_sheet(spec["filtered"], "Decision Makers")
    print(f"  worked columns ({len(worked_header)}): {worked_header}")
    print(f"  decision maker columns ({len(dm_header)}): {dm_header}")

    master = read_master(spec["master"])
    source_columns = list(master.columns)
    source_url = source_columns[1]
    worked_set = set(worked_header)
    extra_columns = [column for column in source_columns if column not in worked_set]
    out_columns = worked_header + extra_columns + [FILTER_COLUMN]
    source_for = {column: match_source(column, source_columns) for column in worked_header}
    research_columns = [column for column, source in source_for.items() if source is None]
    print(f"  mapped from directory: { {k: v for k, v in source_for.items() if v} }")
    print(f"  research columns left blank unless the filtered workbook has the store: {research_columns}")
    print(f"  appended source columns: {extra_columns}")

    count_index = column_index(worked_header, "Website Count", "Website Pages Count")
    traffic_index = column_index(worked_header, "Semrush Organic Traffic")
    worked_url_index = column_index(worked_header, "Root Domain Link", "Website Link", "Website")

    filtered_by_key = {}
    for values in filtered_rows:
        key = url_key(values[worked_url_index])
        if not key:
            raise ValueError(f"filtered row missing URL in {spec['filtered'].name}")
        if key in filtered_by_key:
            raise ValueError(f"duplicate filtered URL key {key}")
        filtered_by_key[key] = values

    directory_keys = {}
    rows = []
    collisions = 0
    researched_rows = 0
    yes = 0
    for record in master.itertuples(index=False, name=None):
        raw = dict(zip(source_columns, record))
        key = url_key(raw[source_url])
        if key in directory_keys:
            collisions += 1
        else:
            directory_keys[key] = len(rows)
        filtered = filtered_by_key.get(key)
        if filtered is not None:
            worked_values = list(filtered)
            researched_rows += 1
        else:
            worked_values = []
            for column in worked_header:
                source_column = source_for[column]
                if source_column is None:
                    worked_values.append(None)
                else:
                    worked_values.append(display_value(source_column, raw[source_column]))
        extras = [display_value(column, raw[column]) for column in extra_columns]
        flag = passes_research_filter(worked_values[count_index], worked_values[traffic_index])
        yes += flag == "Yes"
        rows.append(worked_values + extras + [flag])
    if collisions:
        print(f"  URL-key collisions (both directory rows kept): {collisions}")

    missing_filtered = [key for key in filtered_by_key if key not in directory_keys]
    if missing_filtered:
        raise SystemExit(f"{spec['file']}: {len(missing_filtered)} filtered stores are not in the directory")

    expected = EXPECTED[spec["file"]]
    if len(rows) != expected:
        raise SystemExit(f"{spec['file']}: row count {len(rows)} != {expected}")

    people_rows, people_skipped = build_people_rows(spec, directory_keys, dm_header, dm_rows)
    if people_skipped:
        raise SystemExit(f"{spec['file']}: {people_skipped} filtered decision makers are not in the directory")

    excluded_cols, excluded_rows = load_excluded(spec["directory"])
    print(f"  excluded rows {len(excluded_rows)} from {spec['directory'].name}")

    wb = Workbook()
    master_ws = wb.active
    master_ws.title = "Master Prospects"
    write_rows(master_ws, out_columns, rows)
    people_ws = wb.create_sheet("Decision Makers")
    write_rows(people_ws, dm_header, people_rows)
    if excluded_rows:
        excluded_ws = wb.create_sheet("Excluded")
        write_rows(excluded_ws, excluded_cols, excluded_rows, full_body=len(excluded_rows) <= 5000)

    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / spec["file"]
    wb.save(destination)
    print(
        f"  wrote {destination.name}: master {len(rows)} researched {researched_rows} "
        f"yes {yes} people {len(people_rows)} excluded {len(excluded_rows)}"
    )
    return {
        "file": spec["file"],
        "master": len(rows),
        "people": len(people_rows),
        "excluded": len(excluded_rows),
        "yes": yes,
        "researched": researched_rows,
        "expected": expected,
        "header": out_columns,
        "worked_header": worked_header,
        "extra_columns": extra_columns,
        "dm_header": dm_header,
        "research_columns": research_columns,
        "filtered": spec["filtered"],
        "source_columns": source_columns,
    }


def verify_one(result: dict):
    path = OUT / result["file"]
    wb = load_workbook(path, read_only=True, data_only=True)
    if "Master Prospects" not in wb.sheetnames or wb.sheetnames[0] != "Master Prospects":
        wb.close()
        raise SystemExit(f"{result['file']}: first sheet is not Master Prospects ({wb.sheetnames})")
    ws = wb["Master Prospects"]
    iterator = ws.iter_rows(values_only=True)
    header = clean_header(next(iterator))
    expected_header = result["worked_header"] + result["extra_columns"] + [FILTER_COLUMN]
    if header != expected_header:
        wb.close()
        raise SystemExit(f"{result['file']}: header mismatch\n got {header}\n want {expected_header}")
    worked_width = len(result["worked_header"])
    research_indexes = [result["worked_header"].index(name) for name in result["research_columns"]]
    url_index = column_index(header, "Root Domain Link", "Website Link", "Website")
    count_index = column_index(header, "Website Count", "Website Pages Count")
    traffic_index = column_index(header, "Semrush Organic Traffic")
    flag_index = header.index(FILTER_COLUMN)

    filtered_header, filtered_rows = read_sheet(result["filtered"], "Master Prospects")
    if filtered_header != result["worked_header"]:
        wb.close()
        raise SystemExit(f"{result['file']}: filtered header changed while building")
    filtered_url = column_index(filtered_header, "Root Domain Link", "Website Link", "Website")
    filtered_by_key = {url_key(row[filtered_url]): row for row in filtered_rows}

    dm_ws = wb["Decision Makers"]
    dm_iterator = dm_ws.iter_rows(values_only=True)
    dm_header = clean_header(next(dm_iterator))
    if dm_header != result["dm_header"]:
        wb.close()
        raise SystemExit(f"{result['file']}: Decision Makers header mismatch\n got {dm_header}\n want {result['dm_header']}")
    dm_count = 0
    dm_seen = []
    for row in dm_iterator:
        values = list(row[: len(dm_header)])
        if any(cell is not None and str(cell).strip() for cell in values):
            dm_count += 1
            dm_seen.append(values)

    count = 0
    yes = 0
    researched_keys = set()
    for row in iterator:
        values = list(row[: len(header)])
        if not any(cell is not None and str(cell).strip() for cell in values):
            continue
        count += 1
        flag = values[flag_index]
        if flag not in {"Yes", "No"}:
            wb.close()
            raise SystemExit(f"{result['file']}: bad filter flag {flag!r} on data row {count}")
        yes += flag == "Yes"
        expected_flag = passes_research_filter(values[count_index], values[traffic_index])
        if flag != expected_flag:
            wb.close()
            raise SystemExit(
                f"{result['file']}: flag {flag} != {expected_flag} "
                f"count={values[count_index]!r} traffic={values[traffic_index]!r}"
            )
        key = url_key(values[url_index])
        worked = values[:worked_width]
        filtered = filtered_by_key.get(key)
        if filtered is not None:
            researched_keys.add(key)
            if list(worked) != list(filtered):
                wb.close()
                raise SystemExit(f"{result['file']}: researched row does not match filtered workbook for {values[url_index]}")
        else:
            for index in research_indexes:
                if worked[index] is not None:
                    wb.close()
                    raise SystemExit(
                        f"{result['file']}: invented research value in {result['worked_header'][index]} for {values[url_index]}"
                    )
    wb.close()
    if count != result["expected"]:
        raise SystemExit(f"{result['file']}: openpyxl row count {count} != {result['expected']}")
    if researched_keys != set(filtered_by_key):
        missing = set(filtered_by_key) - researched_keys
        extra = researched_keys - set(filtered_by_key)
        raise SystemExit(f"{result['file']}: researched keys missing {len(missing)} extra {len(extra)}")
    if dm_count != result["people"]:
        raise SystemExit(f"{result['file']}: Decision Makers rows {dm_count} != {result['people']}")

    filtered_dm_header, filtered_dm_rows = read_sheet(result["filtered"], "Decision Makers")
    if filtered_dm_header != dm_header:
        raise SystemExit(f"{result['file']}: filtered Decision Makers header changed")
    link_at = column_index(dm_header, "Website Link", "Root Domain Link", "Website")
    dm_keys = {person_identity(dm_header, row, url_key(row[link_at])) for row in dm_seen}
    missing_people = 0
    filtered_link_at = column_index(filtered_dm_header, "Website Link", "Root Domain Link", "Website")
    for row in filtered_dm_rows:
        identity = person_identity(filtered_dm_header, row, url_key(row[filtered_link_at]))
        if identity not in dm_keys:
            missing_people += 1
    if missing_people:
        raise SystemExit(f"{result['file']}: {missing_people} filtered decision makers missing from FULL")
    print(f"  verified {result['file']}: rows {count} researched {len(researched_keys)} yes {yes} people {dm_count}")


def write_readme(results: list[dict]):
    lines = [
        "# Full prospect directories",
        "",
        "These workbooks contain every accepted store in the directory. They have no page-count cutoff and no Semrush traffic cutoff.",
        "",
        "Master Prospects starts with the same columns, in the same order, as the filtered workbook for that market. Stores that were already researched keep those worked values. Stores that were not researched have the directory fields filled (name, URL, Semrush traffic, website count, count method, and any other worked header that has a directory source) and the research columns blank. Directory columns whose names are not already in that worked header are appended after it. `Passes Research Filter` is the last column. It is Yes only when the website count is blank (including `Not found`) or at least 500 and Semrush organic traffic is at least 1,000. Traffic that is missing or under 1,000 is No. Rows marked No stay in Master Prospects.",
        "",
        "Decision Makers uses the filtered workbook's columns and the people already researched for that store. Stores with no research have no people row. Excluded collects the directory reject lists that include a reason (fashion exclusions, unverified candidates, removed platform subdomains, and StoreLeads rejections). Those rows are not in Master Prospects. The first Excluded column, Exclusion list, names the source list.",
        "",
        "| File | Master rows | Decision-maker rows | Excluded rows | Download |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        url = f"{RAW}/{result['file']}"
        lines.append(
            f"| `{result['file']}` | {result['master']} | {result['people']} | {result['excluded']} | {url} |"
        )
    lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    selected = set(sys.argv[1:])
    specs = [spec for spec in MARKETS if not selected or spec["file"] in selected or spec["file"].replace("_FULL.xlsx", "") in selected]
    before = {spec["filtered"]: file_md5(spec["filtered"]) for spec in specs}
    results = [build_one(spec) for spec in specs]
    print("\nVERIFY")
    for result in results:
        verify_one(result)
    after = {spec["filtered"]: file_md5(spec["filtered"]) for spec in specs}
    changed = [path.name for path, digest in before.items() if after[path] != digest]
    if changed:
        raise SystemExit(f"filtered workbooks changed: {changed}")
    if not selected:
        write_readme(results)
    print("\nSUMMARY")
    for result in results:
        print(
            f"{result['file']}\tmaster={result['master']}\tpeople={result['people']}\t"
            f"excluded={result['excluded']}\tyes={result['yes']}\tresearched={result['researched']}"
        )
        print("HEADER\t" + " | ".join(result["header"]))


if __name__ == "__main__":
    main()

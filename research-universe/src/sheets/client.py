from __future__ import annotations

import json
import os
import pathlib
from typing import Any

import gspread


def _make_gc() -> gspread.Client:
    raw = os.environ["GOOGLE_SERVICE_ACCOUNT"]
    info = json.loads(raw if raw.strip().startswith("{") else pathlib.Path(raw).read_text())
    return gspread.service_account_from_dict(info)


class SheetsClient:
    def __init__(self, sheet_id: str | None = None) -> None:
        self._gc = _make_gc()
        self._sheet = self._gc.open_by_key(sheet_id or os.environ["GOOGLE_SHEET_ID"])

    def _ws(self, tab_name: str) -> gspread.Worksheet:
        return self._sheet.worksheet(tab_name)

    def read_tab(self, tab_name: str) -> list[dict[str, Any]]:
        return self._ws(tab_name).get_all_records()

    def append_rows(self, tab_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        ws = self._ws(tab_name)
        headers = ws.row_values(1)
        values = [[str(r.get(h) or "") for h in headers] for r in rows]
        ws.append_rows(values, value_input_option="RAW")

    def update_rows(
        self, tab_name: str, updates: list[dict[str, Any]], key_col: str
    ) -> None:
        if not updates:
            return
        ws = self._ws(tab_name)
        all_values = ws.get_all_values()
        if len(all_values) < 2:
            return
        headers = all_values[0]
        if key_col not in headers:
            raise ValueError(f"{key_col!r} not in {tab_name!r} headers")
        key_idx = headers.index(key_col)

        key_to_rows: dict[str, list[int]] = {}
        for i, row in enumerate(all_values[1:], start=2):
            val = row[key_idx] if key_idx < len(row) else ""
            key_to_rows.setdefault(val, []).append(i)

        batch: list[dict] = []
        for upd in updates:
            key_val = str(upd.get(key_col, ""))
            for row_num in key_to_rows.get(key_val, []):
                for col_name, value in upd.items():
                    if col_name in headers:
                        col_num = headers.index(col_name) + 1
                        batch.append(
                            {
                                "range": gspread.utils.rowcol_to_a1(row_num, col_num),
                                "values": [[str(value) if value is not None else ""]],
                            }
                        )
        if batch:
            ws.batch_update(batch)

    def overwrite_tab(self, tab_name: str, rows: list[dict[str, Any]]) -> None:
        ws = self._ws(tab_name)
        headers = ws.row_values(1)
        data = [headers] + [[str(r.get(h) or "") for h in headers] for r in rows]
        ws.clear()
        ws.update(values=data, range_name="A1")

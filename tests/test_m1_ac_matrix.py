"""PT-15: the committed M1 AC matrix stays in sync with the PRD count and real tests."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "docs" / "m1-acceptance-report.md"

ROW_RE = re.compile(
    r"^\|\s*(?P<id>R\d+-AC\d+)\s*\|\s*(?P<req>.*?)\s*\|\s*(?P<scope>M[12])\s*\|\s*(?P<proof>.*?)\s*\|\s*(?P<result>.*?)\s*\|$",
    re.MULTILINE,
)


def _rows() -> list[dict[str, str]]:
    text = REPORT.read_text(encoding="utf-8")
    start = text.index("<!-- ac-matrix -->")
    end = text.index("<!-- /ac-matrix -->")
    table = text[start:end]
    rows = [match.groupdict() for match in ROW_RE.finditer(table)]
    assert rows, "AC matrix table not found or unparseable"
    return rows


def test_matrix_counts_match_the_prd():
    rows = _rows()
    ids = [row["id"] for row in rows]
    assert len(ids) == 48, f"expected 48 AC rows, found {len(ids)}: {ids}"
    assert len(set(ids)) == 48
    m1 = [row for row in rows if row["scope"] == "M1"]
    m2 = [row for row in rows if row["scope"] == "M2"]
    assert len(m1) == 42
    assert len(m2) == 6
    assert all(row["id"].startswith(("R12-", "R14-")) for row in m2)
    assert all(not row["id"].startswith(("R12-", "R14-")) for row in m1)


def test_every_m1_row_is_pass_with_a_real_test():
    rows = _rows()
    missing = []
    for row in rows:
        if row["scope"] == "M2":
            assert "excluded" in row["result"].lower(), row
            continue
        assert row["result"].lower().startswith("pass"), row
        proofs = [part.strip().strip("`") for part in row["proof"].split(";;") if part.strip()]
        assert proofs, row
        for proof in proofs:
            if "::" not in proof:
                missing.append(f"{row['id']}: no test name in {proof!r}")
                continue
            path, name = proof.split("::", 1)
            file = REPO / path
            if not file.is_file():
                missing.append(f"{row['id']}: missing file {path}")
                continue
            source = file.read_text(encoding="utf-8")
            if path.endswith(".py"):
                if f"def {name}(" not in source:
                    missing.append(f"{row['id']}: {path} has no def {name}")
            elif path.endswith((".ts", ".tsx")):
                if f"test('{name}'" not in source and f'test("{name}"' not in source:
                    missing.append(f"{row['id']}: {path} has no test({name!r})")
            else:
                missing.append(f"{row['id']}: unrecognized proof path {path}")
    assert missing == []


def test_m2_rows_are_not_claimed_as_pass():
    for row in _rows():
        if row["scope"] == "M2":
            assert "pass" not in row["result"].lower()

"""R13 (PT-05): the protected test-content keyword screen, unit level."""

from __future__ import annotations

import pytest

from psychtool.core.protected import find_protected, is_protected


@pytest.mark.parametrize(
    "text",
    [
        "The examiner reproduced the test items verbatim.",
        "All test item wording is listed below.",
        "Here is one test question from the battery.",
        "Several test questions are transcribed here.",
        "Compare against the published norm table.",
        "Norm table: raw 12 = T 55.",
        "Norm tables are reproduced below.",
        "Scores were interpreted using the age norms.",
        "the age norm was applied",
        "Use the normative table for this age band.",
        "normative tables by grade",
        "Scoring rules: two points per correct response.",
        "Follow the scoring rule exactly.",
        "The scoring key marks item 4 reversed.",
        "Apply the scoring keys in order.",
        "See scoring criteria appendix B.",
        "Use the conversion table to a standard score.",
        "conversion tables for subtests",
        "See the raw-score table on page 3.",
        "See the raw score tables on page 3.",
        # Chinese terms match as substrings.
        "以下为测验原题，请勿外流。",
        "常模资料见附件。",
        "请遵循计分规则。",
        "评分标准见下表。",
        "分数换算表如下。",
        # Case-insensitive.
        "NORM TABLE",
        "TEST ITEMS",
    ],
)
def test_positive_matches(text):
    assert is_protected(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "The results were within the normal range.",
        "She normally finishes her homework on time.",
        "Abnormal findings were absent.",
        "The room was an enormous classroom.",
        "The data were normalized before analysis.",
        "Normative data were not collected for this tool.",
        "The test results were discussed with the family.",
        "He is scoring well in math this term.",
        "The tested items arrived late from the vendor.",
        "",
    ],
)
def test_negative_non_matches(text):
    assert is_protected(text) is False


def test_find_protected_returns_indexes():
    passages = [
        "A perfectly ordinary synthetic paragraph.",
        "Norm table: raw 12 = T 55.",
        "Another normal paragraph.",
        "常模资料见附件。",
    ]
    assert find_protected(passages) == [1, 3]
    assert find_protected([]) == []

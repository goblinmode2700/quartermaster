import pytest
from wcwidth import wcswidth

from quartermaster import render as display
from quartermaster.render import render


def report(labels):
    return {
        "accounts": [
            {
                "label": label,
                "provider": "claude",
                "freshness": "unknown",
                "ageSeconds": None,
                "windows": [],
            }
            for label in labels
        ]
    }


@pytest.mark.parametrize("width,height", [(32, 6), (80, 24), (20, 4)])
def test_default_labels_remain_distinct(width, height):
    lines = render(report(["slot-1", "slot-2"]), width, height)
    assert lines[1].split()[0] == "slot-1"
    assert lines[2].split()[0] == "slot-2"
    assert all(len(line) <= width for line in lines)


@pytest.mark.parametrize(
    "width,height,label",
    [
        (80, 24, "example-account-with-a-descriptive-label"),
        (32, 6, "account-one"),
        (20, 4, "example-1"),
        (80, 4, "example-account-with-a-descriptive-label"),
    ],
)
def test_label_uses_available_width(width, height, label):
    lines = render(report([label]), width, height)
    assert lines[1].split()[0] == label
    assert all(len(line) <= width for line in lines)


def test_quota_columns_align_and_overlong_labels_are_marked():
    lines = render(report(["a" * 100, "slot-2"]), 32, 6)
    assert lines[1].split()[0].endswith("~")
    assert lines[1].index("!") == lines[2].index("!")
    assert lines[1].endswith("?")
    assert all(len(line) <= 32 for line in lines)


def test_wide_labels_preserve_terminal_width_and_column_alignment():
    lines = render(report(["账户一账户二账户三", "slot-2"]), 32, 6)
    assert lines[1].split()[0].endswith("~")
    assert wcswidth(lines[1]) == 32
    assert lines[1].index("!") != lines[2].index("!")
    assert wcswidth(lines[1][: lines[1].index("!")]) == wcswidth(lines[2][: lines[2].index("!")])
    assert all(wcswidth(line) <= 32 for line in lines)


def test_long_reset_clocks_keep_their_space(monkeypatch):
    monkeypatch.setattr(display, "_reset", lambda account: "117:19")
    lines = render(report(["slot-1", "slot-2"]), 32, 6)
    assert lines[1].split()[0] == "slot-1"
    assert lines[2].split()[0] == "slot-2"
    assert lines[1].endswith("117:19")
    assert lines[2].endswith("117:19")
    assert all(len(line) <= 32 for line in lines)


def test_resize_restores_full_label():
    data = report(["example-account-with-long-label"])
    assert render(data, 32, 6)[1].split()[0].endswith("~")
    assert render(data, 80, 6)[1].split()[0] == data["accounts"][0]["label"]


@pytest.mark.parametrize("label", ["\n" + "a" * 100, "\x1b[2Jaccount", "account\tname", "a\u202eb"])
def test_control_characters_cannot_change_terminal_layout(label):
    lines = render(report([label, "slot-2"]), 32, 6)
    assert all(0 <= wcswidth(line) <= 32 for line in lines)
    assert "\n" not in lines[1] and "\x1b" not in lines[1] and "\t" not in lines[1]


def test_large_compact_frame_shows_all_accounts():
    lines = render(report([f"account-{i}" for i in range(11)]), 80, 24)
    assert sum(line.startswith("account-") for line in lines) == 11

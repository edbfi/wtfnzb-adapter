from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

from wtfnzb_adapter import newznab, parsing
from wtfnzb_adapter.models import AdapterError, Snapshot
from wtfnzb_adapter.service import category_matches

if TYPE_CHECKING:
    from pathlib import Path

ZONE = ZoneInfo("Europe/Copenhagen")


def test_rss_metadata_and_translation(evidence: Path) -> None:
    releases = parsing.rss((evidence / "rss-all.xml").read_bytes())
    assert len(releases) == 50
    assert releases[0].size == 1894614079
    assert releases[0].category == 5040
    assert releases[0].date.isoformat().endswith("+02:00")
    assert not releases[0].approximate_size
    xml = newznab.feed(
        Snapshot(releases, "test"), "https://adapter.example", "adapter-test-key", 2, 3
    )
    root = parsing.xml(xml)
    assert len(root.findall("channel/item")) == 3
    page = root.find(f"channel/{{{parsing.NS}}}response")
    assert page is not None and page.get("total") == "50"
    assert b"wtfnzb.example" not in xml
    assert b"REDACTED" not in xml


@pytest.mark.parametrize(
    "name",
    [
        "archive-casablanca-67.html",
        "archive-casablanca-4.html",
        "session-no-match-control.html",
        "session-isolated-90s.html",
    ],
)
def test_partial_is_not_success(evidence: Path, name: str) -> None:
    with pytest.raises(AdapterError, match="incomplete"):
        _ = parsing.archive((evidence / name).read_bytes(), ZONE)


def test_completed_archive_and_count(evidence: Path) -> None:
    raw = (evidence / "archive-matrix-100.html").read_bytes()
    candidates = parsing.archive(raw, ZONE)
    assert len(candidates) == 100
    assert all("Matrix" in c.title for c in candidates)
    with pytest.raises(AdapterError, match="count"):
        _ = parsing.archive(raw.replace(b"found 100 results", b"found 99 results"), ZONE)
    candidate = next(c for c in candidates if c.guid == "b97e0f32280cc4e17903ec53fe411c12")
    release = parsing.detail(
        (evidence / "detail-matrix-metadata.html").read_bytes(), candidate, ZONE
    )
    assert release.category == 2040  # Site says HD even though title says 2160p.
    assert release.size == 31847182499
    assert release.approximate_size
    assert release.title == candidate.title


def test_series_rows_preserve_titles_and_metadata(evidence: Path) -> None:
    rows = (evidence / "series-release-rows.html").read_bytes()
    with pytest.raises(AdapterError, match="incomplete"):
        _ = parsing.series(rows, ZONE)
    releases = parsing.series(b"<html>" + rows + b"</html>", ZONE)
    assert len(releases) == 2
    assert releases[0].title.startswith("Outlander.Blood.of.My.Blood.S02E01")
    assert releases[0].category == 5040
    assert all(r.approximate_size for r in releases)


def test_missing_conflicting_categories_and_size(evidence: Path) -> None:
    raw = (evidence / "rss-all.xml").read_bytes()
    with pytest.raises(AdapterError, match="category"):
        _ = parsing.rss(raw.replace(b"browse?t=5040", b"browse?other=5040"))
    with pytest.raises(AdapterError, match="disagree"):
        _ = parsing.rss(raw.replace(b'name="category" value=""', b'name="category" value="2040"'))
    with pytest.raises(AdapterError):
        _ = parsing.rss(
            raw.replace(b'length="1894614079"', b'length="0"').replace(
                b'value="1894614079"', b'value="0"'
            )
        )


def test_category_mapping_and_parent_filter() -> None:
    assert parsing.CATEGORY_REMAP[1090] == 1140
    assert parsing.CATEGORY_REMAP[8020] != 8020
    assert category_matches(5045, (5000,))
    assert not category_matches(5045, (5040,))
    assert category_matches(108020, (8000,))
    caps = parsing.xml(newznab.caps())
    assert caps.find("categories/category/subcat[@id='1140']") is not None


def test_nzb_validation_preserves_content() -> None:
    raw = b'<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb"><file><segments><segment bytes="1" number="0">sample</segment></segments></file></nzb>'
    assert parsing.nzb(raw) == raw
    with_doctype = (
        b'<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">'
        + raw
    )
    assert parsing.nzb(with_doctype) == with_doctype
    for bad in (b"<html>denied</html>", b"<nzb/>", b'<!DOCTYPE x [<!ENTITY a "x">]><nzb/>'):
        with pytest.raises(AdapterError):
            _ = parsing.nzb(bad)


def test_observed_rounded_zero_size_rows_are_omitted(evidence: Path) -> None:
    raw = (evidence / "series-zero-size-row.html").read_bytes()
    assert parsing.series(b"<html>" + raw + b"</html>", ZONE) == ()

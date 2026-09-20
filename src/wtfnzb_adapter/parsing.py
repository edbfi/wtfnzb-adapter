"""Parsers reject missing metadata and incomplete streams instead of inventing it."""

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup, Tag
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from wtfnzb_adapter.models import AdapterError, Candidate, Release

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

NS = "http://www.newznab.com/DTD/2010/feeds/attributes/"
GUID = re.compile(r"^[a-f0-9]{32}$")
DATE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
CATEGORY_REMAP = {1090: 1140, 1100: 1180, **{n: 100000 + n for n in range(8020, 8070, 10)}}


def xml(raw: bytes) -> ET.Element:
    try:
        return SafeET.fromstring(raw, forbid_entities=True, forbid_external=True)
    except ET.ParseError, DefusedXmlException:
        raise AdapterError("Upstream XML is malformed or contains prohibited entities") from None


def attribute(tag: Tag, name: str) -> str:
    value = tag.get(name)
    return value if isinstance(value, str) else ""


def guid_from_link(link: str) -> str:
    parts = urlsplit(link).path.split("/")
    for part in parts:
        value = part.removesuffix(".nzb")
        if GUID.fullmatch(value):
            return value
    raise AdapterError("Release has no valid GUID")


def category_from_html(node: Tag | BeautifulSoup) -> int:
    ids: set[int] = set()
    for anchor in node.select('a[href*="?t="]'):
        values = parse_qs(urlsplit(attribute(anchor, "href")).query).get("t", [])
        if len(values) == 1 and values[0].isdigit():
            ids.add(int(values[0]))
    if len(ids) != 1:
        raise AdapterError("Release category is missing or conflicting")
    upstream = ids.pop()
    return CATEGORY_REMAP.get(upstream, upstream)


def rounded_size(value: str) -> int:
    match = re.search(r"\b([\d.]+)\s*(KB|MB|GB|TB)\b", value)
    if not match:
        raise AdapterError("Release size is missing or malformed")
    factor = {"KB": 1024, "MB": 1048576, "GB": 1073741824, "TB": 1099511627776}[match[2]]
    try:
        size = int(Decimal(match[1]) * factor)
    except InvalidOperation:
        raise AdapterError("Release size is malformed") from None
    return size


def local_date(value: str, zone: ZoneInfo) -> datetime:
    match = DATE.search(value)
    if not match:
        raise AdapterError("Release date is missing or malformed")
    try:
        return datetime.fromisoformat(match[0]).replace(tzinfo=zone)
    except ValueError:
        raise AdapterError("Release date is invalid") from None


def rss(raw: bytes) -> tuple[Release, ...]:
    root = xml(raw)
    if root.tag != "rss" or root.find("channel") is None:
        raise AdapterError("Upstream did not return an RSS channel")
    releases: list[Release] = []
    try:
        for item in root.findall("channel/item"):
            attrs = {a.get("name"): a.get("value", "") for a in item.findall(f"{{{NS}}}attr")}
            title = item.findtext("title", "").strip()
            enclosure = item.find("enclosure")
            if not title or enclosure is None:
                raise AdapterError("RSS release has no title or enclosure")
            size = int(attrs.get("size") or enclosure.get("length", ""))
            date = parsedate_to_datetime(attrs.get("usenetdate") or item.findtext("pubDate", ""))
            if date.tzinfo is None or size <= 0:
                raise AdapterError("RSS release has an invalid size or timezone")
            description = BeautifulSoup(item.findtext("description", ""), "html.parser")
            category = category_from_html(description)
            explicit = attrs.get("category", "")
            if explicit and CATEGORY_REMAP.get(int(explicit), int(explicit)) != category:
                raise AdapterError("RSS category sources disagree")
            releases.append(
                Release(guid_from_link(item.findtext("guid", "")), title, date, size, category)
            )
    except ValueError, TypeError, OverflowError:
        raise AdapterError("RSS release metadata is malformed") from None
    return deduplicate(releases)


def archive(raw: bytes, zone: ZoneInfo) -> tuple[Candidate, ...]:
    soup = BeautifulSoup(raw, "html.parser")
    finished = soup.select_one(".finished")
    if finished is None or soup.select_one(".timeout-error, .error"):
        raise AdapterError("Archive search is incomplete; upstream omitted its completion marker")
    count = re.search(r"found (\d+) results", finished.get_text())
    rows = soup.select(".result .line")
    if count is None or int(count[1]) != len(rows):
        raise AdapterError("Archive completion count does not match its results")
    candidates: list[Candidate] = []
    for row in rows:
        fields = row.get_text().split("|")
        link = row.select_one('a[href*="/details/"]')
        if len(fields) < 3 or not fields[1].strip() or link is None:
            raise AdapterError("Archive release is malformed")
        candidates.append(
            Candidate(
                guid_from_link(attribute(link, "href")),
                fields[1].strip(),
                local_date(fields[0], zone),
            )
        )
    return tuple({c.guid: c for c in candidates}.values())


def detail(raw: bytes, candidate: Candidate, zone: ZoneInfo) -> Release:
    soup = BeautifulSoup(raw, "html.parser")
    fields: dict[str, Tag] = {}
    for label in soup.select(".th"):
        sibling = label.find_next_sibling("div")
        if isinstance(sibling, Tag):
            fields[label.get_text(strip=True).rstrip(":")] = sibling
    if not {"Category", "Size", "Posted"} <= fields.keys():
        raise AdapterError("Detail page lacks release metadata (session may have expired)")
    return Release(
        candidate.guid,
        candidate.title,
        local_date(attribute(fields["Posted"], "title"), zone),
        rounded_size(fields["Size"].get_text()),
        category_from_html(fields["Category"]),
        True,
    )


def series(raw: bytes, zone: ZoneInfo) -> tuple[Release, ...]:
    if b"</html>" not in raw.lower():
        raise AdapterError("Series page is incomplete")
    soup = BeautifulSoup(raw, "html.parser")
    if soup.select_one('input[type="password"]'):
        raise AdapterError("Session expired", 100, 503)
    releases: list[Release] = []
    rows = soup.select('.data-row[id^="guid"]')
    if not rows:
        raise AdapterError("Series page contains no recognized release rows")
    for row in rows:
        link = row.select_one('a[title="View details"]')
        if link is None:
            raise AdapterError("Series release has no detail link")
        href = attribute(link, "href")
        title = unquote(urlsplit(href).path.split("/", 3)[-1])
        dates = [
            attribute(tag, "title")
            for tag in row.select("[title]")
            if DATE.fullmatch(attribute(tag, "title"))
        ]
        sizes = [
            tag.get_text(" ")
            for tag in row.select(".nowrap")
            if re.search(r"\d\s*(?:MB|GB|KB|TB)", tag.get_text())
        ]
        if len(dates) != 1 or len(sizes) != 1:
            raise AdapterError("Series metadata is missing or ambiguous")
        releases.append(
            Release(
                guid_from_link(href),
                title,
                local_date(dates[0], zone),
                rounded_size(sizes[0]),
                category_from_html(row),
                True,
            )
        )
    return deduplicate([release for release in releases if release.size > 0])


def deduplicate(releases: list[Release]) -> tuple[Release, ...]:
    return tuple(
        sorted({r.guid: r for r in releases}.values(), key=lambda r: (r.date, r.guid), reverse=True)
    )


def nzb(raw: bytes) -> bytes:
    root = xml(raw)
    ns = "{http://www.newzbin.com/DTD/2003/nzb}"
    if root.tag != f"{ns}nzb" or not root.findall(f"{ns}file"):
        raise AdapterError("Download is not an NZB with files")
    for file in root.findall(f"{ns}file"):
        if not file.findall(f"{ns}segments/{ns}segment"):
            raise AdapterError("NZB file has no segments")
    return raw


def tokens(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", value.casefold())


def matches(title: str, query: str) -> bool:
    haystack = tokens(title)
    needle = tokens(query)
    return all(part in haystack for part in needle)

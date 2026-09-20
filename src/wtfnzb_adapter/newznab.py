import xml.etree.ElementTree as ET
from email.utils import format_datetime
from importlib.resources import files
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import msgspec

from wtfnzb_adapter.parsing import CATEGORY_REMAP, NS

if TYPE_CHECKING:
    from wtfnzb_adapter.models import AdapterError, Snapshot

ET.register_namespace("newznab", NS)


class Category(msgspec.Struct):
    id: int
    label: str


CATEGORIES = msgspec.json.decode(
    files("wtfnzb_adapter").joinpath("categories.json").read_bytes(), type=list[Category]
)
KNOWN_CATEGORIES = {CATEGORY_REMAP.get(c.id, c.id) for c in CATEGORIES}


def serialize(root: ET.Element) -> bytes:
    output = BytesIO()
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return output.getvalue()


def error(exc: AdapterError) -> bytes:
    return serialize(ET.Element("error", {"code": str(exc.code), "description": str(exc)}))


def caps() -> bytes:
    root = ET.Element("caps")
    _ = ET.SubElement(
        root, "server", {"title": "WTFNZB Adapter (experimental)", "version": "0.1.0"}
    )
    _ = ET.SubElement(root, "limits", {"max": "100", "default": "5"})
    searching = ET.SubElement(root, "searching")
    for mode, params in (("search", "q"), ("tv-search", "q,season,ep"), ("movie-search", "q")):
        _ = ET.SubElement(searching, mode, {"available": "yes", "supportedParams": params})
    categories = ET.SubElement(root, "categories")
    parents: dict[int, ET.Element] = {}
    for category in CATEGORIES:
        if category.id % 1000 == 0:
            parents[category.id] = ET.SubElement(
                categories,
                "category",
                {"id": str(category.id), "name": category.label.removeprefix("All ")},
            )
    for category in CATEGORIES:
        if category.id % 1000:
            _ = ET.SubElement(
                parents[category.id // 1000 * 1000],
                "subcat",
                {"id": str(CATEGORY_REMAP.get(category.id, category.id)), "name": category.label},
            )
    return serialize(root)


def feed(snapshot: Snapshot, public_url: str, api_key: str, offset: int, limit: int) -> bytes:
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "WTFNZB Adapter"
    ET.SubElement(channel, "description").text = snapshot.scope
    ET.SubElement(channel, "link").text = public_url
    _ = ET.SubElement(
        channel, f"{{{NS}}}response", {"offset": str(offset), "total": str(len(snapshot.releases))}
    )
    for release in snapshot.releases[offset : offset + limit]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = release.title
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = release.guid
        url = public_url + "/api?" + urlencode({"t": "get", "id": release.guid, "apikey": api_key})
        ET.SubElement(item, "link").text = url
        ET.SubElement(item, "pubDate").text = format_datetime(release.date)
        ET.SubElement(item, "description").text = (
            "Size estimated from rounded upstream display"
            if release.approximate_size
            else "Exact upstream RSS size"
        )
        _ = ET.SubElement(
            item,
            "enclosure",
            {"url": url, "length": str(release.size), "type": "application/x-nzb"},
        )
        for name, value in (
            ("category", str(release.category)),
            ("size", str(release.size)),
            ("usenetdate", format_datetime(release.date)),
        ):
            _ = ET.SubElement(item, f"{{{NS}}}attr", {"name": name, "value": value})
    return serialize(root)

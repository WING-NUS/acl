# -*- coding: utf-8 -*-
#
# Copyright 2019 Marcel Bollmann <marcel@bollmann.me>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools as it
import logging
import os
import re
import requests
import shutil

from lxml import etree
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape
from typing import Tuple, Optional
from zlib import crc32

from .people import PersonName
from . import data


xml_escape_or_none = lambda t: None if t is None else xml_escape(t)


def is_newstyle_id(anthology_id):
    return anthology_id[0].isdigit()  # New-style IDs are year-first


def is_journal(anthology_id):
    if is_newstyle_id(anthology_id):
        # TODO: this function is sometimes called with "full_id", sometimes with
        # "collection_id", so we're not using `deconstruct_anthology_id` here at
        # the moment
        venue = anthology_id.split("-")[0].split(".")[-1]
        return venue in data.JOURNAL_IDS
    else:
        return anthology_id[0] in ("J", "Q")


def is_volume_id(anthology_id):
    collection_id, volume_id, paper_id = deconstruct_anthology_id(anthology_id)
    return paper_id == "0"


def is_valid_id(id_):
    """
    Determines whether the identifier has a valid Anthology identifier format (paper or volume).
    """
    match = re.match(r"([A-Z]\d{2})-(\d{1,4})", id_)
    if not re.match(r"[A-Z]\d{2}-\d{1,3}", id_):
        return False

    first, rest = match.groups()

    if len(rest) != 4:
        if (
            first.startswith("W")
            or first == "C69"
            or (first == "D19" and int(rest[0]) >= 5)
        ):
            return len(rest) == 2
        else:
            return len(rest) == 1

    return True


def build_anthology_id(
    collection_id: str, volume_id: str, paper_id: Optional[str] = None
) -> str:
    """
    Transforms collection id, volume id, and paper id to a width-padded
    Anthology ID. e.g., ('P18', '1', '1') -> P18-1001.
    """
    if is_newstyle_id(collection_id):
        if paper_id is not None:
            return f"{collection_id}-{volume_id}.{paper_id}"
        else:
            return f"{collection_id}-{volume_id}"
    # pre-2020 IDs
    if (
        collection_id.startswith("W")
        or collection_id == "C69"
        or (collection_id == "D19" and int(volume_id) >= 5)
    ):
        anthology_id = f"{collection_id}-{int(volume_id):02d}"
        if paper_id is not None:
            anthology_id += f"{int(paper_id):02d}"
    else:
        anthology_id = f"{collection_id}-{int(volume_id):01d}"
        if paper_id is not None:
            anthology_id += f"{int(paper_id):03d}"

    return anthology_id


def test_url_code(url):
    """
    Test a URL, returning the result.
    """
    headers = {'user-agent': 'acl-anthology/0.0.1'}
    r = requests.head(url, headers=headers, allow_redirects=True)
    return r


def test_url(url):
    """
    Tests a URL, returning True if the URL exists, and False otherwise.
    """
    return test_url_code(url).status_code == requests.codes.ok


def retrieve_url(remote_url: str, local_path: str):
    """
    Saves a URL to a local path. Can handle cookies, e.g., those
    used downloading PDFs from MIT Press (TACL, CL).

    :param remote_url: The URL to download from. Currently supports http only.
    :param local_path: Where to save the file to.
    """
    outdir = os.path.dirname(local_path)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    if remote_url.startswith("http"):
        import ssl
        import urllib.request

        cookieProcessor = urllib.request.HTTPCookieProcessor()
        opener = urllib.request.build_opener(cookieProcessor)
        request = urllib.request.Request(
            remote_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (X11; U; Linux i686) Gecko/20071127 Firefox/2.0.0.11'
            },
        )

        with opener.open(request, timeout=1000) as url, open(
            local_path, mode="wb"
        ) as input_file_fh:
            input_file_fh.write(url.read())
    else:
        shutil.copyfile(remote_url, local_path)

    return True


def deconstruct_anthology_id(anthology_id: str) -> Tuple[str, str, str]:
    """
    Transforms an Anthology ID into its constituent collection id, volume id, and paper id
    parts. e.g,

        P18-1007 -> ('P18', '1',  '7')
        W18-6310 -> ('W18', '63', '10')
        D19-1001 -> ('D19', '1',  '1')
        D19-5702 -> ('D19', '57', '2')

    Also can deconstruct Anthology volumes:

        P18-1 -> ('P18', '1', None)
        W18-63 -> ('W18', '63', None)

    For Anthology IDs prior to 2020, the volume ID is the first digit after the hyphen, except
    for the following situations, where it is the first two digits:

    - All collections starting with 'W'
    - The collection "C69"
    - All collections in "D19" where the first digit is >= 5
    """
    collection_id, rest = anthology_id.split("-")
    if is_newstyle_id(anthology_id):
        if "." in rest:
            volume_id, paper_id = rest.split(".")
        else:
            volume_id, paper_id = rest, None
        return (collection_id, volume_id, paper_id)
    # pre-2020 IDs
    if (
        collection_id.startswith("W")
        or collection_id == "C69"
        or (collection_id == "D19" and int(rest[0]) >= 5)
    ):
        if len(rest) == 4:
            return (collection_id, str(int(rest[0:2])), str(int(rest[2:])))
        else:  # Possible Volume only identifier
            return (collection_id, str(int(rest)), None)
    else:
        if len(rest) == 4:
            return (collection_id, str(int(rest[0:1])), str(int(rest[1:])))
        else:  # Possible Volume only identifier
            return (collection_id, str(int(rest)), None)


def stringify_children(node):
    """Returns the full content of a node, including tags.

    Used for nodes that can have mixed text and HTML elements (like <b> and <i>)."""
    return "".join(
        chunk
        for chunk in it.chain(
            (xml_escape_or_none(node.text),),
            it.chain(
                *(
                    (
                        etree.tostring(child, with_tail=False, encoding=str),
                        xml_escape_or_none(child.tail),
                    )
                    for child in node.getchildren()
                )
            ),
            (xml_escape_or_none(node.tail),),
        )
        if chunk
    ).strip()


def remove_extra_whitespace(text):
    return re.sub(" +", " ", text.replace("\n", "").strip())


def infer_url(filename, template=data.CANONICAL_URL_TEMPLATE):
    """If URL is relative, return the full Anthology URL.
    Returns the canonical URL by default, unless a different
    template is provided."""

    assert (
        "{}" in template or "%s" in template
    ), "template has no substitution text; did you pass a prefix by mistake?"

    if urlparse(filename).netloc:
        return filename
    return template.format(filename)


def infer_attachment_url(filename, parent_id=None):
    if urlparse(filename).netloc:
        return filename
    # Otherwise, treat it as an internal filename
    if parent_id is not None and not filename.startswith(parent_id):
        logging.error(
            "attachment must begin with paper ID '{}', but is '{}'".format(
                parent_id, filename
            )
        )
    return infer_url(filename, data.ATTACHMENT_TEMPLATE)


def infer_year(collection_id):
    """Infer the year from the collection ID.

    Many paper entries do not explicitly contain their year.  This function assumes
    that the paper's collection identifier follows the format 'xyy', where x is
    some letter and yy are the last two digits of the year of publication.
    """
    if is_newstyle_id(collection_id):
        return collection_id.split(".")[0]

    assert (
        len(collection_id) == 3
    ), f"Couldn't infer year: unknown volume ID format '{collection_id}' ({type(collection_id)})"
    digits = collection_id[1:]
    if int(digits) >= 60:
        year = "19{}".format(digits)
    else:
        year = "20{}".format(digits)

    return year


_MONTH_TO_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def month_str2num(text):
    """Convert a month string to a number, e.g. February -> 2

    Returns None if the string doesn't correspond to a month.

    Not using Python's datetime here since its behaviour depends on the system
    locale."""
    return _MONTH_TO_NUM.get(text.lower(), None)


class SeverityTracker(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level=level)
        self.highest = logging.NOTSET

    def emit(self, record):
        if record.levelno > self.highest:
            self.highest = record.levelno


def clean_whitespace(text, strip="left"):
    old_text = text
    if text is not None:
        text = re.sub(r" +", " ", text)
        if strip == "left" or strip == "both":
            text = text.lstrip()
        if strip == "right" or strip == "both":
            text = text.rstrip()
    return text


def indent(elem, level=0, internal=False):
    """
    Enforces canonical indentation: two spaces,
    with each tag on a new line, except that 'author', 'editor',
    'title', and 'booktitle' tags are placed on a single line.

    Adapted from https://stackoverflow.com/a/33956544 .
    """
    # tags that have no internal linebreaks (including children)
    oneline = elem.tag in ("author", "editor", "title", "booktitle", "variant")

    elem.text = clean_whitespace(elem.text)

    if len(elem):  # children
        # Set indent of first child for tags with no text
        if not oneline and (not elem.text or not elem.text.strip()):
            elem.text = "\n" + (level + 1) * "  "

        if not elem.tail or not elem.tail.strip():
            if level:
                elem.tail = "\n" + level * "  "
            else:
                elem.tail = "\n"

        # recurse
        for child in elem:
            indent(child, level + 1, internal=oneline)

        # Clean up the last child
        if oneline:
            child.tail = clean_whitespace(child.tail, strip="right")
        elif not child.tail or not child.tail.strip():
            child.tail = "\n" + level * "  "
    else:
        elem.text = clean_whitespace(elem.text, strip="both")

        if internal:
            elem.tail = clean_whitespace(elem.tail, strip="none")
        elif not elem.tail or not elem.tail.strip():
            elem.tail = "\n" + level * "  "


def parse_element(xml_element):
    attrib = {}
    if xml_element is None:
        return attrib

    for element in xml_element:
        # parse value
        tag = element.tag.lower()
        if tag in ("abstract", "title", "booktitle"):
            tag = "xml_{}".format(tag)
            value = element
        elif tag == "attachment":
            value = {
                "filename": element.text,
                "type": element.get("type", "attachment"),
                "url": element.text,
            }
        elif tag in ("author", "editor"):
            id_ = element.attrib.get("id", None)
            value = (PersonName.from_element(element), id_)
        elif tag == "erratum":
            value = {"value": element.text, "id": element.get("id"), "url": element.text}
        elif tag == "revision":
            value = {
                "value": element.get("href"),
                "id": element.get("id"),
                "url": element.get("href"),
                "explanation": element.text,
            }
        elif tag == "mrf":
            value = {"filename": element.text, "src": element.get("src")}
        elif tag == "video":
            # Treat videos the same way as other attachments
            tag = "attachment"
            # Skip videos where permission was not granted (these should be marked as private anyway in Vimeo)
            if element.get("permission", "true") == "false":
                continue
            value = {
                "filename": element.get("href"),
                "type": element.get("tag", "video"),
                "url": element.get("href"),
            }
        elif tag in ("dataset", "software"):
            value = {"filename": element.text, "type": tag, "url": element.text}
            tag = "attachment"
        else:
            value = element.text

        if tag == "url":
            # Set the URL (canonical / landing page for Anthology)
            value = infer_url(element.text)

            # Add a PDF link with, converting relative URLs to canonical ones
            attrib["pdf"] = (
                element.text
                if urlparse(element.text).netloc
                else data.PDF_LOCATION_TEMPLATE.format(element.text)
            )

        if tag in data.LIST_ELEMENTS:
            try:
                attrib[tag].append(value)
            except KeyError:
                attrib[tag] = [value]
        else:
            attrib[tag] = value

    return attrib


def make_simple_element(tag, text=None, attrib=None, parent=None, namespaces=None):
    """Convenience function to create an LXML node"""
    el = (
        etree.Element(tag, nsmap=namespaces)
        if parent is None
        else etree.SubElement(parent, tag)
    )
    if text:
        el.text = text
    if attrib:
        for key, value in attrib.items():
            el.attrib[key] = value
    return el


def compute_hash(value: bytes) -> str:
    checksum = crc32(value) & 0xFFFFFFFF
    return f"{checksum:08x}"


def compute_hash_from_file(path: str) -> str:
    with open(path, "rb") as f:
        return compute_hash(f.read())

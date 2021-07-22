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

import iso639
import logging as log

from .utils import (
    build_anthology_id,
    parse_element,
    infer_url,
    infer_attachment_url,
    remove_extra_whitespace,
    is_journal,
    is_volume_id,
)
from . import data

# For bibliography export
from .formatter import bibtex_encode, bibtex_make_entry


class Paper:
    def __init__(self, paper_id, ingest_date, volume, formatter):
        self.parent_volume = volume
        self.formatter = formatter
        self._id = paper_id
        self._ingest_date = ingest_date
        self._bibkey = False
        self.is_volume = paper_id == "0"

        # initialize metadata with keys inherited from volume
        self.attrib = {}
        for key, value in volume.attrib.items():
            # Only inherit 'editor' for frontmatter
            if (key == "editor" and not self.is_volume) or key in (
                "collection_id",
                "booktitle",
                "id",
                "meta_data",
                "meta_journal_title",
                "meta_volume",
                "meta_issue",
                "sigs",
                "venues",
                "meta_date",
                "url",
                "pdf",
            ):
                continue

            self.attrib[key] = value

    def from_xml(xml_element, *args):
        ingest_date = xml_element.get("ingest-date", data.UNKNOWN_INGEST_DATE)

        # Default to paper ID "0" (for front matter)
        paper = Paper(xml_element.get("id", "0"), ingest_date, *args)

        # Set values from parsing the XML element (overwriting
        # and changing some initialized from the volume metadata)
        for key, value in parse_element(xml_element).items():
            if key == "author" and "editor" in paper.attrib:
                del paper.attrib["editor"]
            paper.attrib[key] = value

        # Frontmatter title is the volume 'booktitle'
        if paper.is_volume:
            paper.attrib["xml_title"] = paper.attrib["xml_booktitle"]
            paper.attrib["xml_title"].tag = "title"

        # Create URL field if not present. But see https://github.com/acl-org/acl-anthology/issues/997.
        if "url" not in paper.attrib:
            paper.attrib["url"] = infer_url(paper.full_id)

        # Remove booktitle for frontmatter and journals
        if paper.is_volume or is_journal(paper.full_id):
            del paper.attrib["xml_booktitle"]

        # Expand URLs with paper ID
        for tag in ("revision", "erratum"):
            if tag in paper.attrib:
                for item in paper.attrib[tag]:
                    if not item["url"].startswith(paper.full_id):
                        log.error(
                            "{} must begin with paper ID '{}', but is '{}'".format(
                                tag, paper.full_id, item["url"]
                            )
                        )
                    item["url"] = data.PDF_LOCATION_TEMPLATE.format(item["url"])

        if "attachment" in paper.attrib:
            for item in paper.attrib["attachment"]:
                item["url"] = infer_attachment_url(item["url"], paper.full_id)

        paper.attrib["title"] = paper.get_title("plain")
        paper.attrib["booktitle"] = paper.get_booktitle("plain")

        if "editor" in paper.attrib:
            if paper.is_volume:
                if "author" in paper.attrib:
                    log.warn(
                        "Paper {} has both <editor> and <author>; ignoring <author>".format(
                            paper.full_id
                        )
                    )
                # Proceedings editors are considered authors for their front matter
                paper.attrib["author"] = paper.attrib["editor"]
                del paper.attrib["editor"]
            else:
                log.warn(
                    "Paper {} has <editor> but is not a proceedings volume; ignoring <editor>".format(
                        paper.full_id
                    )
                )
        if "pages" in paper.attrib:
            if paper.attrib["pages"] is not None:
                paper._interpret_pages()
            else:
                del paper.attrib["pages"]

        if "author" in paper.attrib:
            paper.attrib["author_string"] = ", ".join(
                [x[0].full for x in paper.attrib["author"]]
            )

        # if "withdrawn" in paper.attrib:
        #     paper.attrib["withdrawn"] = True
        paper.attrib["thumbnail"] = data.PDF_THUMBNAIL_LOCATION_TEMPLATE.format(
            paper.full_id
        )

        return paper

    def _interpret_pages(self):
        """Splits up 'pages' field into first and last page, if possible.

        This is used for metadata in the generated HTML."""
        for s in ("--", "-", "–"):
            if self.attrib["pages"].count(s) == 1:
                self.attrib["page_first"], self.attrib["page_last"] = self.attrib[
                    "pages"
                ].split(s)
                self.attrib["pages"] = self.attrib["pages"].replace(s, "–")
                return

    @property
    def ingest_date(self):
        """Inherit publication date from parent, but self overrides. May be undefined."""
        if self._ingest_date:
            return self._ingest_date
        if self.parent_volume:
            return self.parent_volume.ingest_date
        return data.UNKNOWN_INGEST_DATE

    @property
    def collection_id(self):
        return self.parent_volume.collection_id

    @property
    def volume_id(self):
        return self.parent_volume.volume_id

    @property
    def paper_id(self):
        return self._id

    @property
    def full_id(self):
        return self.anthology_id

    @property
    def anthology_id(self):
        return build_anthology_id(self.collection_id, self.volume_id, self.paper_id)

    @property
    def bibkey(self):
        if not self._bibkey:
            self._bibkey = self.full_id  # fallback
        return self._bibkey

    @bibkey.setter
    def bibkey(self, value):
        self._bibkey = value

    @property
    def bibtype(self):
        if is_journal(self.full_id):
            return "article"
        elif self.is_volume:
            return "proceedings"
        else:
            return "inproceedings"

    @property
    def parent_volume_id(self):
        if self.parent_volume is not None:
            return self.parent_volume.full_id
        return None

    @property
    def has_abstract(self):
        return "xml_abstract" in self.attrib

    @property
    def is_withdrawn(self) -> bool:
        return "withdrawn" in self.attrib

    @property
    def isbn(self):
        return self.attrib.get("isbn", None)

    @property
    def langcode(self):
        """Returns the ISO-639 language code, if present"""
        return self.attrib.get("language", None)

    @property
    def language(self):
        """Returns the language name, if present"""
        lang = None
        if self.langcode:
            lang = iso639.languages.get(part3=self.langcode).name
        return lang

    def get(self, name, default=None):
        try:
            return self.attrib[name]
        except KeyError:
            return default

    def get_title(self, form="xml"):
        """Returns the paper title, optionally formatting it.

        Accepted formats:
          - xml:   Include any contained XML tags unchanged
          - plain: Strip all XML tags, returning only plain text
          - html:  Convert XML tags into valid HTML tags
          - latex: Convert XML tags into LaTeX commands
        """
        return self.formatter(self.get("xml_title"), form)

    def get_abstract(self, form="xml"):
        """Returns the abstract, optionally formatting it.

        See `get_title()` for details.
        """
        return self.formatter(self.get("xml_abstract"), form, allow_url=True)

    def get_booktitle(self, form="xml", default=""):
        """Returns the booktitle, optionally formatting it.

        See `get_title()` for details.
        """
        if "xml_booktitle" in self.attrib:
            return self.formatter(self.get("xml_booktitle"), form)
        elif self.parent_volume is not None:
            return self.parent_volume.get("title")
        else:
            return default

    def as_bibtex(self, concise=False):
        """Return the BibTeX entry for this paper."""
        # Build BibTeX entry
        bibkey = self.bibkey
        bibtype = self.bibtype
        entries = [("title", self.get_title(form="latex"))]
        for people in ("author", "editor"):
            if people in self.attrib:
                entries.append(
                    (people, "  and  ".join(p.as_bibtex() for p, _ in self.get(people)))
                )
        if is_journal(self.full_id):
            entries.append(
                ("journal", bibtex_encode(self.parent_volume.get("meta_journal_title")))
            )
            journal_volume = self.parent_volume.get(
                "meta_volume", self.parent_volume.get("volume")
            )
            if journal_volume:
                entries.append(("volume", journal_volume))
            journal_issue = self.parent_volume.get(
                "meta_issue", self.parent_volume.get("issue")
            )
            if journal_issue:
                entries.append(("number", journal_issue))
        else:
            # not is_journal(self.full_id)
            if "xml_booktitle" in self.attrib:
                entries.append(("booktitle", self.get_booktitle(form="latex")))
            elif bibtype != "proceedings":
                entries.append(("booktitle", self.parent_volume.get_title(form="latex")))
        for entry in ("month", "year", "address", "publisher", "note"):
            if self.get(entry) is not None:
                entries.append((entry, bibtex_encode(self.get(entry))))
        for entry in ("url", "doi"):
            if entry in self.attrib:
                # don't want latex escapes such as
                # doi = "10.1162/coli{\_}a{\_}00008",
                entries.append((entry, self.get(entry)))
        if "pages" in self.attrib:
            entries.append(("pages", self.get("pages").replace("–", "--")))
        if "xml_abstract" in self.attrib and not concise:
            entries.append(("abstract", self.get_abstract(form="latex")))
        if self.language:
            entries.append(("language", self.language))
        if self.isbn:
            entries.append(("ISBN", self.isbn))

        # Serialize it
        return bibtex_make_entry(bibkey, bibtype, entries)

    def as_dict(self):
        value = self.attrib.copy()
        value["paper_id"] = self.paper_id
        value["parent_volume_id"] = self.parent_volume_id
        value["bibkey"] = self.bibkey
        value["bibtype"] = self.bibtype
        value["language"] = self.language
        return value

    def items(self):
        return self.attrib.items()

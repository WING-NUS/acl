#!/usr/bin/env python3
"""
Quick script for ingesting LiLT metadata.
Author: Matt Post
July 2020
"""

import csv
import lxml.etree as etree
import os
import shutil
import ssl
import sys
import urllib.request

import anthology
from anthology.utils import make_simple_element, indent, compute_hash_from_file
from datetime import datetime
from normalize_anth import normalize
from likely_name_split import NameSplitter


def dump_collection(tree, collection_file):
    indent(tree.getroot())
    tree.write(collection_file, encoding="UTF-8", xml_declaration=True, with_tail=True)


def main(args):
    anth = anthology.Anthology(importdir=os.path.join(args.anthology, "data"))
    splitter = NameSplitter(anth)

    paper_nums = {}
    venue = "lilt"
    prev_year = None
    prev_volume = None
    for row in csv.DictReader(args.tsv_file, delimiter='\t'):
        year = row.get("year")
        month = row.get("month")
        issue = row.get("issue#", "")
        abstract = row.get("abstract")
        collection_id = f"{year}.lilt"
        if year != prev_year:
            if prev_year is not None:
                dump_collection(
                    tree,
                    os.path.join(args.anthology, "data", "xml", f"{prev_year}.lilt.xml"),
                )

            tree = etree.ElementTree(
                make_simple_element("collection", attrib={"id": collection_id})
            )
            root = tree.getroot()
        prev_year = year

        volume_name = row.get("Volume#")
        if volume_name != prev_volume:
            volume = make_simple_element(
                "volume", attrib={"id": volume_name}, parent=root
            )
            meta = make_simple_element("meta", parent=volume)
            make_simple_element("booktitle", row.get("Booktitle"), parent=meta)
            make_simple_element("publisher", "CSLI Publications", parent=meta)
            make_simple_element("year", year, parent=meta)
            if month:
                make_simple_element("month", month, parent=meta)

        paper_num = paper_nums[volume_name] = paper_nums.get(volume_name, 0) + 1

        prev_volume = volume_name

        paper = make_simple_element("paper", attrib={"id": str(paper_num)}, parent=volume)
        paper_id = f"{collection_id}-{volume_name}.{paper_num}"
        make_simple_element("title", row.get("title"), parent=paper)
        authors = row.get("authors")
        for author_name in authors.split(" and "):
            author = make_simple_element("author", parent=paper)
            surname, givenname = splitter.best_split(author_name)
            make_simple_element("first", givenname, parent=author)
            make_simple_element("last", surname, parent=author)

        if abstract != "":
            make_simple_element("abstract", abstract, parent=paper)
        if issue != "":
            make_simple_element("issue", issue, parent=paper)

        for node in paper:
            normalize(node, "latex")

        dest_dir = f"{args.anthology_files_path}/lilt"
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        source_path = os.path.join(
            "pdf", row.get("PDF").replace("\\", "/").replace("../", "")
        )
        if os.path.exists(source_path):
            dest_path = os.path.join(
                dest_dir, f"{collection_id}-{volume_name}.{paper_num}.pdf"
            )
            shutil.copy(source_path, dest_path)
            print(f"Copying {source_path} to {dest_path}", file=sys.stderr)
            os.chmod(dest_path, 0o644)
            checksum = compute_hash_from_file(dest_path)
            make_simple_element("url", paper_id, attrib={"hash": checksum}, parent=paper)

    dump_collection(
        tree, os.path.join(args.anthology, "data", "xml", f"{collection_id}.xml")
    )


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('tsv_file', type=argparse.FileType("r"))
    parser.add_argument(
        '--anthology',
        default=f"{os.environ.get('HOME')}/code/acl-anthology",
        help="Path to Anthology repo (cloned from https://github.com/acl-org/acl-anthology)",
    )
    parser.add_argument(
        '--anthology-files-path',
        default=f"{os.environ.get('HOME')}/anthology-files/pdf",
        help="Path to Anthology files (Default: ~/anthology-files",
    )
    args = parser.parse_args()

    main(args)

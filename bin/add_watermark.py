#! /usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2020 Matt Post <post@cs.jhu.edu>
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

"""
Takes an Anthology ID, downloads the PDF, and produces a revision PDF
with a "WITHDRAWN" watermark, as well as a note at the top pointing
to the paper page.

TODO:
* assumes no existing revision, should check if existing ones
* update XML automatically
* rename as retract_paper.py or something
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from string import Template

from anthology.utils import (
    compute_hash_from_file,
    deconstruct_anthology_id,
    retrieve_url,
    is_newstyle_id,
)
from anthology.data import CANONICAL_URL_TEMPLATE, PDF_LOCATION_TEMPLATE

from datetime import datetime

template = Template(
    r"""\documentclass{article}
\usepackage[printwatermark]{xwatermark}
\usepackage{xcolor}
\usepackage{graphicx}
\usepackage{pdfpages}
\usepackage{hyperref}
\hypersetup{plainpages=false,
            pdfpagemode=none,
            colorlinks=true,
            unicode=true
}

% "allpages" didn't work
\newwatermark[pages=1-1000,color=red!80,angle=45,scale=3,xpos=0,ypos=0]{WITHDRAWN}

% set A4
\setlength{\paperwidth}{21cm}
\setlength{\paperheight}{29.7cm}

\special{papersize=21cm,29.7cm}
\pdfpageheight\paperheight
\pdfpagewidth\paperwidth
\pagestyle{plain}

\begin{document}

\AddToShipoutPicture{%
  \setlength{\unitlength}{1mm}
  % center box at (x, y) millimeters from bottom-left corner
  \put(105,290){\makebox(0,0){This paper was withdrawn. For more information, see \url{$url}.}}
}

\includepdf[pages=-]{$file}

\end{document}"""
)


def main(args):
    page = CANONICAL_URL_TEMPLATE.format(args.anthology_id)
    url = PDF_LOCATION_TEMPLATE.format(args.anthology_id)
    _, pdf_file = tempfile.mkstemp(suffix=".pdf")
    retrieve_url(url, pdf_file)

    tex_file = f"{args.anthology_id}v2.tex"
    with open(tex_file, "w") as f:
        print(template.substitute(file=pdf_file, url=page), file=f)

    command = f"pdflatex {tex_file}"
    retcode = subprocess.call(command, shell=True)

    now = datetime.now()
    date = f"{now.year}-{now.month:02d}-{now.day:02d}"

    new_pdf = f"{tex_file}".replace(".tex", ".pdf")
    orig_hash = compute_hash_from_file(pdf_file)
    new_hash = compute_hash_from_file(new_pdf)
    print(f'<revision id="1" href="{args.anthology_id}v1" hash="{orig_hash}" />')
    print(
        f'<revision id="2" href="{args.anthology_id}v2" hash="{new_hash}" date="{date}">Paper withdrawn.</revision>'
    )

    collection_id, venue_name, paper_id = deconstruct_anthology_id(args.anthology_id)

    if is_newstyle_id(args.anthology_id):
        venue_name = collection_id.split(".")[1]
        output_dir = os.path.join(args.anthology_dir, "pdf", venue_name)
    else:
        output_dir = os.path.join(
            args.anthology_dir, "pdf", collection_id[0], collection_id
        )

    # Make sure directory exists
    if not os.path.exists(output_dir):
        print(f"-> Creating directory {output_dir}", file=sys.stderr)
        os.makedirs(output_dir)

    shutil.copyfile(pdf_file, os.path.join(output_dir, f"{args.anthology_id}v1.pdf"))
    shutil.copyfile(new_pdf, os.path.join(output_dir, new_pdf))

    os.remove(pdf_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("anthology_id")
    parser.add_argument(
        "--anthology-dir",
        default=os.path.join(os.environ["HOME"], "anthology-files"),
        help="Anthology web directory root.",
    )
    args = parser.parse_args()

    main(args)

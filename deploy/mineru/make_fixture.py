"""Generate a synthetic, non-sensitive two-page PDF for deployment acceptance."""

import argparse
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def create(path):
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    pages = [
        [
            "Network AIOps MinerU Deployment Test",
            "R2 BGP neighbor disconnected.",
            "Interface eth1 packet loss is 6.06 percent.",
            "These records are synthetic deployment fixtures.",
        ],
        [
            "Network interface measurements",
            "Device | Interface | Packet loss",
            "R2 | eth1 | 6.06 percent",
            "R3 | eth1 | 0.10 percent",
            "Verify page ordering and structured extraction.",
        ],
    ]
    for lines in pages:
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        content = b"BT /F1 16 Tf 50 760 Td 28 TL\n"
        for line in lines:
            content += b"(" + line.encode("ascii") + b") Tj T*\n"
        stream = DecodedStreamObject()
        stream.set_data(content + b"ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer.write(path)
    print(f"Synthetic PDF created: {path}; pages=2")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    create(parser.parse_args().path)

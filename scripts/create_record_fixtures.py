"""Reproducible positive/negative synthetic records; never patient data."""
from pathlib import Path
import argparse
import pymupdf

TEXTS = {
    'completed-record.pdf': 'SYNTHETIC TEST DATA - NOT FOR CLINICAL USE\nWellness follow-up record\nReport Status: Final\nPatient ID: DEMO-1\nPatient Name: Fictional Person\nMedication: Exampledrug 5 mg once daily\nA1C: 6.1%\nReference range for A1C: below 5.7%\nCurrent zone: Green\nVariant: c.123A>G\n',
    'reference-only.pdf': 'SYNTHETIC TEST DATA - NOT FOR CLINICAL USE\nReference-only laboratory report\nReport Status: Final\nPatient ID: DEMO-2\nReference range for A1C: below 5.7%\nMedication:\nRecommend genetic testing.\n',
}


def create(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in TEXTS.items():
        path = directory / name
        if path.exists():
            with pymupdf.open(path) as doc:
                if len(doc) != 1 or doc[0].get_text().strip() != text.strip():
                    raise ValueError(f'Refusing to overwrite different existing fixture: {name}')
            continue
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), text, fontsize=11)
            doc.save(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/record-corpus'))
    create(parser.parse_args().output)

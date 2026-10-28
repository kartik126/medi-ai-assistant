"""Copy an explicitly selected local session's public PDFs into an ignored test corpus."""
import argparse
import hashlib
from pathlib import Path
import shutil
import sys
from uuid import UUID
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import get_settings
from backend.db import Database

PUBLIC_FILES = ['Asthma-Action-Plan-2020_rev_508.pdf', 'new_dash.pdf',
                'On-your-way-to-preventing-type-2-diabetes.pdf']


def prepare(sid, destination, source_dir=None):
    sources = []
    if source_dir is not None:
        sources = [(name, source_dir / name) for name in PUBLIC_FILES]
    else:
        settings = get_settings()
        db = Database(settings.database_url)
        db.open()
        try:
            with db.connection() as conn:
                rows = conn.execute('SELECT document_id,filename,sha256 FROM documents WHERE session_id=%s', (sid,)).fetchall()
            found = {row['filename']: row for row in rows}
            for name in PUBLIC_FILES:
                if name not in found:
                    raise ValueError(f'Missing required public document: {name}')
                row = found[name]
                source = settings.data_dir / 'sessions' / str(sid) / f"{row['document_id']}.pdf"
                if hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
                    raise ValueError('Stored original PDF does not match its metadata')
                sources.append((name, source))
        finally:
            db.close()
    sources += [(name, Path('data/fixtures') / name) for name in ['training-a.pdf', 'training-b.pdf']]
    # Validate the complete copy operation before writing any corpus files.
    for name, source in sources:
        target = destination / name
        if not source.is_file():
            raise ValueError(f'Missing corpus source: {name}')
        if target.exists() and hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
            raise ValueError(f'Refusing to overwrite a different corpus file: {name}')
    destination.mkdir(parents=True, exist_ok=True)
    for name, source in sources:
        target = destination / name
        if not target.exists():
            shutil.copyfile(source, target)
    print(f'Prepared {len(sources)} local test PDFs. Originals and application sessions unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--session', type=UUID)
    source.add_argument('--source-dir', type=Path, help='Directory containing the three previously supplied public PDFs')
    parser.add_argument('--output', type=Path, default=Path('data/edge-corpus'))
    args = parser.parse_args()
    prepare(args.session, args.output, args.source_dir)

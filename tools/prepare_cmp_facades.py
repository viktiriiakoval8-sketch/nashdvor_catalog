"""Prepare the public CMP base dataset locally with provenance and untouched annotations."""
import hashlib
import json
import zipfile
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://cmp.felk.cvut.cz/~tylecr1/facade/'


def main():
    archive = ROOT/'.facade-data/cmp-base.zip'
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        response = httpx.get(SOURCE+'CMP_facade_DB_base.zip', timeout=120)
        response.raise_for_status()
        archive.write_bytes(response.content)
    out = ROOT/'.facade-data/cmp-base'
    out.mkdir(exist_ok=True)
    rows = []
    with zipfile.ZipFile(archive) as data:
        for name in ('readme.txt','label_names.txt'):
            (out/name).write_bytes(data.read(name))
        for name in sorted(data.namelist()):
            path = Path(name)
            if path.suffix.lower() not in {'.jpg','.png','.xml'}:
                continue
            # Flatten only known image/annotation entries, never extract arbitrary paths.
            if path.parent.as_posix() != 'base' or not path.stem.startswith('cmp_b'):
                raise ValueError('Unexpected archive entry: '+name)
            raw = data.read(name)
            (out/path.name).write_bytes(raw)
            rows.append(dict(file=path.name, sha256=hashlib.sha256(raw).hexdigest()))
    manifest = dict(source=SOURCE, downloadUrl=SOURCE+'CMP_facade_DB_base.zip',
                    archiveSha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    attribution='Radim Tylecek and Radim Sara, Spatial Pattern Templates for Recognition of Objects with Regular Structure, GCPR 2013; CMP, CTU Prague',
                    license='CC BY-SA as stated by publisher; version not explicit in text (3.0 badge)',
                    licenseSource=SOURCE, documentation=SOURCE+'CMP_facade_DB_2013.pdf',
                    changes='None; original files and annotations extracted unchanged',
                    trainingPerformed=False, files=rows)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (out/'ATTRIBUTION.md').write_text(
        '# CMP Facade Database — base\n\n'+manifest['attribution']+'\n\nSource and license statement: '+SOURCE+
        '\n\nPublisher: CC BY-SA (3.0 badge; text does not name version). Original images/annotations unchanged. '+
        'Diagnostic overlays are derived previews under the same license. Preserve this attribution when sharing. '+
        'Images are rectified facades, not representative of all customer house photos. No model training performed.\n',encoding='utf-8')
    print(f'Prepared {len(rows)//3} image/annotation triples: {out}')


if __name__ == '__main__':
    main()

"""Fold <out_dir>/*.entry.json into <out_dir>/manifest.json without Blender.

    python3 merge_manifest.py [out_dir]     # default: $STUDIO_OUT_DIR or ./public/models

Replaces entries with the same id in place and appends new ones, so the order of
an existing manifest is preserved and several generators can run in parallel."""
import json, os, sys
from pathlib import Path
out=Path(sys.argv[1] if len(sys.argv)>1 else os.environ.get('STUDIO_OUT_DIR') or 'public/models')
path=out/'manifest.json'; manifest=json.loads(path.read_text()) if path.exists() else []
for f in sorted(out.glob('*.entry.json')):
 entry=json.loads(f.read_text()); ids=[a['id'] for a in manifest]
 if entry['id'] in ids: manifest[ids.index(entry['id'])]=entry
 else: manifest.append(entry)
path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
print(f'{len(manifest)} assets in {path}')

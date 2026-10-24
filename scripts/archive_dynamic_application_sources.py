"""Retain user screenshots privately and publish content hashes, not images.

Run after the public-source collector. The calculation builder subsequently
uses this public manifest and never requires access to the private snapshots.
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from public_quota_urls import public_url

ROOT = Path(__file__).resolve().parents[1]
BATCH = 'dynamic_applications_20261024'
INPUT = ROOT / 'data/research' / BATCH
PRIVATE = ROOT / 'data/private' / BATCH
SCREENSHOT_IDS = '''450979c7-902f-421c-ad8a-40202aa89edb
02121ec0-94bb-464a-9ac4-f6bde7f16091
9103de00-53d9-4883-af8f-2544fe6b374f
8b747116-a689-4125-a390-1e7dd9d93c5f
7556b016-e588-41ae-9d42-116893973737
6a355a40-a7c2-4bb9-aea7-b56a372f552a
82ba2e1e-3007-40b9-a3f6-ed9c5bc5354d
3d8c4b1e-50a9-47ad-ab0b-6a34c953537e
d02a78ce-dbcd-4f8b-957f-faaa7f65c2d3
62fd6ddd-1e52-42dd-a0ed-f8692d6a7e20
9c6f9914-c0d0-434d-9299-8f27bc2598b8
a5be9639-49eb-448e-b3f4-34780219f4db
f7ab3574-6aee-4444-8867-84c9ea69a2ee
38ae01e9-f47f-4ecd-a3d5-224bb883d08b
0962a472-6510-4b6d-b7c5-21059203e74d
1d990271-a868-4ef5-a636-9e1b77d3fa8b
e0ec2c43-50f5-42fb-b74b-f8601b0e592a
aa3fe774-f2c9-41ff-85cb-b62f0c5b27e9
51df102a-e447-41f2-bc8a-312d44ca5687
61818e05-ef37-43da-8460-edbfc2e0651c
c60c806b-195d-4220-bbc0-1c1a7367a72a
3fc6da2c-d661-478d-b485-88dfccaa2bd4
bcf7caf5-d671-4cb3-8c3e-cfedb7b57117
6920574f-5654-42ba-897e-a527716a3317
e687cc7b-f051-48c9-a3c7-574417ef1556'''.splitlines()


def main():
    captures = []
    for path in sorted((PRIVATE / 'snapshots').glob('*.json')):
        source = json.loads(path.read_text(encoding='utf-8'))
        row = {key: source.get(key) for key in
               ['id', 'school', 'year', 'status', 'collected_at', 'sha256', 'bytes', 'content_type']}
        row['id'] = 'new:' + row['id']
        row['url'] = public_url(source['url'])
        captures.append(row)
    (INPUT / 'source_manifest.json').write_text(
        json.dumps(captures, ensure_ascii=False, indent=2), encoding='utf-8')
    image_dir = PRIVATE / 'screenshots'
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = INPUT / 'screenshot_manifest.json'
    old = {r['page']: r for r in json.loads(manifest_path.read_text(encoding='utf-8'))} if manifest_path.exists() else {}
    images = []
    for page, identifier in enumerate(SCREENSHOT_IDS, 1):
        name = f'codex-clipboard-{identifier}.png'
        destination = image_dir / f'page_{page:02d}.png'
        if not destination.exists():
            source = Path.home() / 'AppData/Local/Temp' / name
            if not source.is_file():
                raise FileNotFoundError(f'Original screenshot {page} is unavailable; retain the existing manifest')
            shutil.copyfile(source, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if page in old and old[page]['sha256'] != digest:
            raise ValueError(f'Immutable screenshot changed: page {page}')
        images.append(dict(page=page, original_filename=name, sha256=digest,
                           first_rank=(page-1)*10+1, last_rank=min(page*10, 242),
                           clock_display='16:30', date_assigned_from_user_submission='2026-10-24',
                           independently_dated=False,
                           preserved_at=old.get(page, {}).get('preserved_at') or
                           datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds')))
    manifest_path.write_text(json.dumps(images, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(public_source_metadata=len(captures), private_screenshots=len(images))))


if __name__ == '__main__':
    main()

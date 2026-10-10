"""Download public roster/statistics images indexed by the source workbook.

Raw images may contain personal identifiers and are therefore stored below
``data/private`` (gitignored).  The public manifest contains only provenance,
hashes, dimensions, and retrieval status.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "data" / "processed" / "program_year_provenance.csv"
DEFAULT_INDEX = ROOT / "data" / "processed" / "mini_program_roster_index.csv"
DEFAULT_RAW = ROOT / "data" / "private" / "roster_assets"
DEFAULT_MANIFEST = ROOT / "data" / "processed" / "roster_asset_manifest.csv"
DEFAULT_AUDIT = ROOT / "data" / "audit" / "roster_asset_collection.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect public roster assets without publishing identifiers.")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def read_targets(path: Path, index_path: Path | None = None) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    targets = {}
    for row in rows:
        if row.get("source_type") != "mini_program_asset" or not row.get("source_url"):
            continue
        key = (row["学校"], row["年份"], row["source_url"])
        targets.setdefault(
            key,
            {
                "school": row["学校"],
                "year": row["年份"],
                "source_url": row["source_url"],
                "source_sheet": row["source_sheet"],
                "source_cell": row["source_cell"],
                "source_row": row["source_row"],
                "authority_grade": row["authority_grade"],
                "artifact_role": row["artifact_role"],
            },
        )
    if index_path and index_path.exists():
        with index_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("in_scope", "")).strip().lower() not in {"true", "1", "yes"}:
                    continue
                url = row.get("repeat_url", "").strip()
                if not url:
                    continue
                key = (row["school"], row["year"], url)
                targets.setdefault(
                    key,
                    {
                        "school": row["school"],
                        "year": row["year"],
                        "source_url": url,
                        "source_sheet": "mini_program_api",
                        "source_cell": "schoolMajorVO.majorRepeatList",
                        "source_row": "",
                        "authority_grade": "secondary_snapshot",
                        "artifact_role": "roster_or_statistics_image",
                    },
                )
    return sorted(targets.values(), key=lambda row: (row["school"], int(row["year"]), row["source_url"]))


def suffix_for(url: str, content_type: str) -> str:
    path_suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if path_suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return path_suffix
    return mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ".bin"


def collect(target: dict, raw_dir: Path) -> dict:
    result = dict(target)
    result.update(
        {
            "retrieval_status": "error",
            "http_status": "",
            "content_type": "",
            "byte_count": "",
            "sha256": "",
            "width": "",
            "height": "",
            "local_private_path": "",
            "retrieved_at": "",
            "error": "",
        }
    )
    try:
        request = urllib.request.Request(
            target["source_url"],
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AppliedStatRiskResearch/1.0)",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read()
            status = int(response.status)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if status != 200:
            raise ValueError(f"unexpected HTTP status {status}")
        digest = hashlib.sha256(payload).hexdigest()
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            image.verify()
        suffix = suffix_for(target["source_url"], content_type)
        school_dir = raw_dir / hashlib.sha256(target["school"].encode("utf-8")).hexdigest()[:12] / target["year"]
        school_dir.mkdir(parents=True, exist_ok=True)
        destination = school_dir / f"{digest[:24]}{suffix}"
        if not destination.exists() or destination.stat().st_size != len(payload):
            destination.write_bytes(payload)
        result.update(
            {
                "retrieval_status": "downloaded",
                "http_status": status,
                "content_type": content_type,
                "byte_count": len(payload),
                "sha256": digest,
                "width": width,
                "height": height,
                "local_private_path": str(destination.relative_to(ROOT)).replace("\\", "/"),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except urllib.error.HTTPError as exc:
        result["http_status"] = exc.code
        result["error"] = f"HTTPError: {exc.reason}"
    except Exception as exc:  # collection audit must retain every failed URL
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def write_manifest(path: Path, rows: list[dict]) -> None:
    fields = [
        "school",
        "year",
        "source_url",
        "source_sheet",
        "source_cell",
        "source_row",
        "authority_grade",
        "artifact_role",
        "retrieval_status",
        "http_status",
        "content_type",
        "byte_count",
        "sha256",
        "width",
        "height",
        "local_private_path",
        "retrieved_at",
        "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    targets = read_targets(args.ledger.resolve(), args.index.resolve())
    if args.limit:
        targets = targets[: args.limit]
    raw_dir = args.raw_dir.resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(collect, target, raw_dir): target for target in targets}
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 25 == 0 or index == len(futures):
                print(f"collected {index}/{len(futures)}")
    results.sort(key=lambda row: (row["school"], int(row["year"]), row["source_url"]))
    write_manifest(args.manifest.resolve(), results)

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_count": len(targets),
        "downloaded": sum(row["retrieval_status"] == "downloaded" for row in results),
        "failed": sum(row["retrieval_status"] != "downloaded" for row in results),
        "school_years_downloaded": len(
            {(row["school"], row["year"]) for row in results if row["retrieval_status"] == "downloaded"}
        ),
        "unique_payloads": len({row["sha256"] for row in results if row["sha256"]}),
        "total_bytes": sum(int(row["byte_count"]) for row in results if row["byte_count"]),
        "privacy": (
            "Raw images remain in gitignored data/private. Public outputs retain only "
            "de-identified derived scores, public URLs, and content hashes."
        ),
        "errors": [
            {key: row[key] for key in ("school", "year", "source_url", "http_status", "error")}
            for row in results
            if row["retrieval_status"] != "downloaded"
        ],
    }
    args.audit.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.audit.resolve().write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

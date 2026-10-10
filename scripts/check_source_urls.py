"""Check the current reachability of unique public provenance URLs.

This is a lightweight audit, not an archival crawler: it prefers HEAD and
downloads at most one byte when a server rejects HEAD.  Existing roster asset
and mini-program retrieval audits are reused instead of requesting them again.
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVENANCE = ROOT / "data" / "processed" / "program_year_provenance.csv"
DEFAULT_REGISTRY = ROOT / "data" / "processed" / "source_registry_urls.csv"
DEFAULT_ROSTERS = ROOT / "data" / "processed" / "roster_asset_manifest.csv"
DEFAULT_INDEX = ROOT / "data" / "processed" / "mini_program_roster_index.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "source_url_audit.csv"
DEFAULT_AUDIT = ROOT / "data" / "audit" / "source_url_audit.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check unique public-source URLs without crawling full content.")
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--rosters", type=Path, default=DEFAULT_ROSTERS)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def collect_targets(provenance: Path, registry: Path) -> list[dict]:
    contexts = defaultdict(lambda: {"schools": set(), "years": set(), "fields": set(), "types": set()})
    for row in read_csv(provenance):
        url = row.get("source_url", "").strip()
        if not url:
            continue
        contexts[url]["schools"].add(row.get("学校", ""))
        contexts[url]["years"].add(row.get("年份", ""))
        contexts[url]["fields"].add(row.get("field_name", ""))
        contexts[url]["types"].add(row.get("source_type", ""))
    for row in read_csv(registry):
        url = row.get("source_url", "").strip()
        if not url:
            continue
        contexts[url]["fields"].add(row.get("covered_fields", ""))
        contexts[url]["types"].add(row.get("source_type", ""))
    targets = []
    for url, context in contexts.items():
        targets.append(
            {
                "source_url": url,
                "source_domain": (urlsplit(url).hostname or "").lower(),
                "source_types": ";".join(sorted(value for value in context["types"] if value)),
                "schools": ";".join(sorted(value for value in context["schools"] if value)),
                "years": ";".join(sorted(value for value in context["years"] if value)),
                "fields": ";".join(sorted(value for value in context["fields"] if value)),
            }
        )
    return sorted(targets, key=lambda row: row["source_url"])


def known_results(rosters: Path, index: Path) -> dict[str, dict]:
    known = {}
    for row in read_csv(rosters):
        url = row.get("source_url", "").strip()
        if not url:
            continue
        known[url] = {
            "check_method": "asset_download",
            "reachability": "reachable" if row.get("retrieval_status") == "downloaded" else "failed",
            "http_status": row.get("http_status", ""),
            "content_type": row.get("content_type", ""),
            "resolved_url": url,
            "content_sha256": row.get("sha256", ""),
            "checked_at": row.get("retrieved_at", ""),
            "error": row.get("error", ""),
        }
    for row in read_csv(index):
        url = row.get("api_url", "").strip()
        if not url:
            continue
        known[url] = {
            "check_method": "api_json_fetch",
            "reachability": "reachable",
            "http_status": "200",
            "content_type": "application/json",
            "resolved_url": url,
            "content_sha256": "",
            "checked_at": row.get("retrieved_at", ""),
            "error": "",
        }
    return known


def request_once(url: str, method: str, timeout: float):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AppliedStatRiskResearch/1.0)",
        "Accept": "text/html,application/pdf,application/json,image/*,*/*;q=0.8",
    }
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    request = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if method == "GET":
            response.read(1)
        return {
            "http_status": int(response.status),
            "content_type": response.headers.get("Content-Type", "").split(";", 1)[0],
            "resolved_url": response.geturl(),
        }


def check(target: dict, timeout: float) -> dict:
    result = {
        **target,
        "check_method": "HEAD",
        "reachability": "failed",
        "http_status": "",
        "content_type": "",
        "resolved_url": "",
        "content_sha256": "",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "error": "",
    }
    try:
        response = request_once(target["source_url"], "HEAD", timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in {400, 403, 405, 500, 501}:
            try:
                response = request_once(target["source_url"], "GET", timeout)
                result["check_method"] = "GET_range"
            except Exception as fallback:
                result["http_status"] = getattr(fallback, "code", exc.code)
                result["error"] = f"{type(fallback).__name__}: {fallback}"
                return result
        else:
            result["http_status"] = exc.code
            result["error"] = f"HTTPError: {exc.reason}"
            return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result.update(response)
    result["reachability"] = "reachable" if 200 <= int(response["http_status"]) < 400 else "failed"
    return result


def main() -> None:
    args = parse_args()
    targets = collect_targets(args.provenance.resolve(), args.registry.resolve())
    known = known_results(args.rosters.resolve(), args.index.resolve())
    results = []
    pending = []
    for target in targets:
        if target["source_url"] in known:
            results.append({**target, **known[target["source_url"]]})
        else:
            pending.append(target)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(check, target, args.timeout): target for target in pending}
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 50 == 0 or index == len(futures):
                print(f"checked {index}/{len(futures)} external URLs", flush=True)
    results.sort(key=lambda row: row["source_url"])
    fields = [
        "source_url",
        "source_domain",
        "source_types",
        "schools",
        "years",
        "fields",
        "check_method",
        "reachability",
        "http_status",
        "content_type",
        "resolved_url",
        "content_sha256",
        "checked_at",
        "error",
    ]
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    with args.output.resolve().open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unique_urls": len(results),
        "reachable": sum(row["reachability"] == "reachable" for row in results),
        "failed_or_blocked": sum(row["reachability"] != "reachable" for row in results),
        "reachability_rate": round(sum(row["reachability"] == "reachable" for row in results) / len(results), 4) if results else None,
        "methods": dict(Counter(row["check_method"] for row in results)),
        "status_codes": dict(Counter(str(row["http_status"] or "none") for row in results)),
        "interpretation": "A failed check may mean anti-bot blocking or temporary outage; it does not by itself invalidate the historical citation.",
    }
    args.audit.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.audit.resolve().write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forecast_freeze import sha256_file, verify_manifest


class ForecastFreezeTest(unittest.TestCase):
    def test_verify_detects_a_changed_frozen_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frozen = root / "example.txt"
            frozen.write_text("baseline", encoding="utf-8")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "path": "example.txt",
                                "sha256": sha256_file(frozen),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(verify_manifest(root, manifest_path), [])
            frozen.write_text("changed", encoding="utf-8")
            self.assertEqual(
                verify_manifest(root, manifest_path), ["changed: example.txt"]
            )


if __name__ == "__main__":
    unittest.main()

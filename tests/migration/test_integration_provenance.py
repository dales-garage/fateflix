import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VendorProvenanceTests(unittest.TestCase):
    def test_vendor_inventory_matches_recorded_content(self):
        vendor = ROOT / "integrations/nixflix/vendor"
        manifest = json.loads((vendor / "provenance.json").read_text())
        actual = {
            str(path.relative_to(vendor)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (vendor / "modules").rglob("*")
            if path.is_file()
            and not {"__pycache__", ".source-cache"}.intersection(path.parts)
        }
        self.assertTrue(actual)
        self.assertEqual(actual, manifest["files"])
        self.assertEqual(
            manifest["repository"], "https://github.com/kiriwalawren/nixflix"
        )


if __name__ == "__main__":
    unittest.main()

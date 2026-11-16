import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VendorProvenanceTests(unittest.TestCase):
    def test_nixflix_is_main_tracking_flake_with_shared_dependencies(self):
        lock = json.loads((ROOT / "flake.lock").read_text())
        node = lock["nodes"][lock["nodes"]["root"]["inputs"]["nixflix"]]
        self.assertTrue(node.get("flake", True))
        self.assertEqual(
            node["original"],
            {
                "owner": "kiriwalawren",
                "repo": "nixflix",
                "ref": "main",
                "type": "github",
            },
        )
        for name in ("nixpkgs", "treefmt-nix", "mkdocs-catppuccin", "vpn-confinement"):
            self.assertEqual(node["inputs"][name], [name])
        for name in ("flake.nix", "modules/flake/inputs.nix"):
            self.assertIn("github:kiriwalawren/nixflix/main", (ROOT / name).read_text())
        self.assertIn(
            "src = inputs.nixflix.outPath;",
            (ROOT / "modules/integrations/nixflix.nix").read_text(),
        )

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

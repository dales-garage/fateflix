import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tarfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "whisparr_update", Path(__file__).resolve().parents[2] / "pkgs/whisparr/update.py"
)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def archive(machine=62):
    stream = io.BytesIO()
    binary = bytearray(20)
    binary[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", binary, 18, machine)
    with tarfile.open(fileobj=stream, mode="w:gz") as t:
        for name, data in {
            "Whisparr/Whisparr": bytes(binary),
            "Whisparr/Whisparr.runtimeconfig.json": b'{"runtimeOptions":{"tfm":"net6.0"}}',
            "Whisparr/Whisparr.dll": b"application",
        }.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            t.addfile(item, io.BytesIO(data))
    return stream.getvalue()


class WhisparrUpdate(unittest.TestCase):
    def test_digest_and_executable_architecture_are_checked(self):
        data = archive()
        self.assertTrue(
            updater.release_hash(
                data, "sha256:" + hashlib.sha256(data).hexdigest()
            ).startswith("sha256-")
        )
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            updater.release_hash(data, "sha256:" + "0" * 64)
        with self.assertRaisesRegex(ValueError, "Linux x64"):
            updater.release_hash(archive(183))

    def test_update_accepts_only_published_v2_release_and_rejects_downgrade(self):
        source = 'version = "2.2.0-release.231"; hash = "sha256-old";'
        release = {
            "tag_name": "v2.2.1-release.240",
            "prerelease": False,
            "draft": False,
            "assets": [{"name": "Whisparr.2.2.1-release.240.linux-x64.tar.gz"}],
        }
        self.assertIn(
            'version = "2.2.1-release.240";',
            updater.updated_source(source, release, lambda _: archive()),
        )
        for changed in [
            {"prerelease": True},
            {"draft": True},
            {"tag_name": "v3.0.0-release.1"},
            {"tag_name": "v2.2.1-develop.240"},
            {"tag_name": "v2.2.0-release.230"},
        ]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                updater.updated_source(
                    source,
                    {**release, **changed},
                    lambda _: self.fail("Untrusted release downloaded"),
                )

    def test_failed_download_does_not_modify_source_and_unchanged_is_noop(self):
        source = 'version = "2.2.0-release.231"; hash = "sha256-old";'
        same = {
            "tag_name": "v2.2.0-release.231",
            "prerelease": False,
            "draft": False,
            "assets": [],
        }
        self.assertEqual(
            updater.updated_source(
                source, same, lambda _: self.fail("Unnecessary download")
            ),
            source,
        )
        with self.assertRaises(OSError):
            updater.updated_source(
                source,
                {
                    **same,
                    "tag_name": "v2.2.1-release.240",
                    "assets": [{"name": "Whisparr.2.2.1-release.240.linux-x64.tar.gz"}],
                },
                lambda _: (_ for _ in ()).throw(OSError("offline")),
            )
        self.assertIn("sha256-old", source)

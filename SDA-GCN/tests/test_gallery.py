import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from runtime.gallery import build_gallery


class GalleryCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "gallery"
        (self.root / "Dai").mkdir(parents=True)
        self.cache = Path(self.temp.name) / "cache" / "gallery.npz"
        self.fingerprint = {"embedding_dimension": 4, "model": "one"}
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def image(self, name, content=b"image"):
        path = self.root / "Dai" / name
        path.write_bytes(content)
        return path

    def extractor(self, path):
        self.calls.append(path.name)
        return np.full(4, len(path.read_bytes()), dtype=np.float32), None

    def build(self, fingerprint=None):
        return build_gallery(self.root, self.cache, fingerprint or self.fingerprint,
                             self.extractor, info=lambda _: None, warning=lambda _: None)

    def test_unchanged_gallery_is_full_cache_hit(self):
        self.image("01.png")
        self.build()
        self.calls.clear()
        _, stats = self.build()
        self.assertEqual(self.calls, [])
        self.assertEqual((stats.cached, stats.recomputed), (1, 0))

    def test_new_and_modified_images_recompute_incrementally(self):
        first = self.image("01.png")
        self.build()
        self.calls.clear()
        self.image("02.png", b"new")
        _, stats = self.build()
        self.assertEqual(self.calls, ["02.png"])
        self.assertEqual((stats.cached, stats.recomputed), (1, 1))
        self.calls.clear()
        first.write_bytes(b"modified-longer")
        _, stats = self.build()
        self.assertEqual(self.calls, ["01.png"])
        self.assertEqual((stats.cached, stats.recomputed), (1, 1))

    def test_deleted_image_is_removed(self):
        first = self.image("01.png")
        self.image("02.png")
        self.build()
        first.unlink()
        self.calls.clear()
        _, stats = self.build()
        self.assertEqual(stats.valid_embeddings, 1)
        self.assertEqual(stats.cached, 1)

    def test_fingerprint_change_invalidates_all_entries(self):
        self.image("01.png")
        self.build()
        self.calls.clear()
        changed = {"embedding_dimension": 4, "model": "two"}
        _, stats = self.build(changed)
        self.assertEqual(self.calls, ["01.png"])
        self.assertEqual(stats.recomputed, 1)

    def test_corrupt_cache_rebuilds_gracefully(self):
        self.image("01.png")
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(b"not an npz")
        _, stats = self.build()
        self.assertEqual(stats.recomputed, 1)
        with np.load(self.cache, allow_pickle=False) as archive:
            self.assertIn("metadata", archive.files)


if __name__ == "__main__":
    unittest.main()

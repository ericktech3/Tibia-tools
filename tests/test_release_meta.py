import os
import tempfile
import unittest

from importlib.machinery import SourceFileLoader

release_meta = SourceFileLoader('release_meta', '.github/scripts/release_meta.py').load_module()


class ReleaseMetaTests(unittest.TestCase):
    def test_read_buildozer_version(self):
        with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8') as fh:
            fh.write('[app]\nversion = 1.2.3\n')
            temp_path = fh.name
        try:
            self.assertEqual(release_meta.read_buildozer_version(temp_path), '1.2.3')
        finally:
            os.unlink(temp_path)

    def test_validate_release_tag(self):
        release_meta.validate_release_tag('v1.2.3', '1.2.3')
        with self.assertRaises(release_meta.ReleaseMetadataError):
            release_meta.validate_release_tag('v2.0.0', '1.2.3')


if __name__ == '__main__':
    unittest.main()

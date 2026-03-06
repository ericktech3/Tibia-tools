import unittest
from pathlib import Path


class RepoHygieneTests(unittest.TestCase):
    def test_no_backup_or_wrapper_files_left(self):
        project_root = Path(__file__).resolve().parents[1]
        forbidden = []
        patterns = ['*.bak', '*.orig']
        for pattern in patterns:
            forbidden.extend(project_root.rglob(pattern))

        forbidden.extend(project_root.glob('core/api.py'))
        forbidden.extend(project_root.glob('core/bosses.py'))
        forbidden.extend(project_root.glob('core/tibia.py'))

        junk_names = {'teste', 'Teste', 'Testa'}
        forbidden.extend(path for path in project_root.rglob('*') if path.name in junk_names)

        self.assertEqual([], sorted({str(path.relative_to(project_root)) for path in forbidden}))


if __name__ == '__main__':
    unittest.main()

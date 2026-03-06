import unittest
from unittest.mock import patch

from services.release_service import (
    GithubReleaseLookupError,
    InvalidGithubRepoUrl,
    build_releases_url,
    fetch_latest_release_for_repo_url,
    has_unseen_release,
)


class ReleaseServiceTests(unittest.TestCase):
    def test_build_releases_url(self):
        self.assertEqual(
            build_releases_url('https://github.com/openai/example-repo'),
            'https://github.com/openai/example-repo/releases',
        )

    def test_invalid_repo_url(self):
        with self.assertRaises(InvalidGithubRepoUrl):
            build_releases_url('https://example.com/nope')

    @patch('services.release_service.fetch_latest_release')
    def test_fetch_latest_release_for_repo_url(self, mock_fetch):
        class Info:
            owner = 'openai'
            repo = 'example-repo'
            tag = 'v1.2.3'
            html_url = 'https://github.com/openai/example-repo/releases/tag/v1.2.3'

        mock_fetch.return_value = Info()
        result = fetch_latest_release_for_repo_url('https://github.com/openai/example-repo')
        self.assertEqual(result.tag, 'v1.2.3')
        self.assertEqual(result.releases_url, 'https://github.com/openai/example-repo/releases')

    @patch('services.release_service.fetch_latest_release', side_effect=ValueError('HTTP 404'))
    def test_fetch_latest_release_for_repo_url_handles_404(self, _mock_fetch):
        with self.assertRaises(GithubReleaseLookupError) as ctx:
            fetch_latest_release_for_repo_url('https://github.com/openai/example-repo')
        self.assertIn('Nenhuma release publicada', str(ctx.exception))

    def test_has_unseen_release(self):
        self.assertTrue(has_unseen_release('v1.0.0', 'v1.1.0'))
        self.assertFalse(has_unseen_release('', 'v1.1.0'))
        self.assertFalse(has_unseen_release('v1.1.0', 'v1.1.0'))


if __name__ == '__main__':
    unittest.main()

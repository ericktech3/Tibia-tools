import unittest
from unittest.mock import Mock, patch

from integrations.github_releases import fetch_latest_release, parse_github_repo
from integrations.tibia_com import parse_tibia_datetime


class IntegrationTests(unittest.TestCase):
    def test_parse_github_repo(self):
        self.assertEqual(
            parse_github_repo("https://github.com/openai/example-repo"),
            ("openai", "example-repo"),
        )
        self.assertIsNone(parse_github_repo("https://example.com/nope"))

    @patch("integrations.github_releases.requests.get")
    def test_fetch_latest_release(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.text = "ok"
        response.json.return_value = {"tag_name": "v1.2.3", "html_url": "https://github.com/openai/example-repo/releases/tag/v1.2.3"}
        mock_get.return_value = response

        info = fetch_latest_release("openai", "example-repo")
        self.assertEqual(info.tag, "v1.2.3")
        self.assertIn("releases/tag", info.html_url)

    def test_parse_tibia_datetime(self):
        dt = parse_tibia_datetime("Jan 22 2026, 10:42:00 CET")
        self.assertIsNotNone(dt)
        self.assertEqual((dt.year, dt.month, dt.day), (2026, 1, 22))


if __name__ == "__main__":
    unittest.main()

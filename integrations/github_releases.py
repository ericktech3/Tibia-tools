from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class GithubReleaseInfo:
    owner: str
    repo: str
    tag: str
    html_url: str


def parse_github_repo(url: str) -> Optional[tuple[str, str]]:
    text = (url or "").strip()
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", text, re.I)
    if not m:
        return None
    owner = m.group(1).strip()
    repo = m.group(2).replace('.git', '').strip()
    if not owner or not repo:
        return None
    return owner, repo


def latest_release_url(owner: str, repo: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def fetch_latest_release(owner: str, repo: str, timeout: int = 15) -> GithubReleaseInfo:
    api = latest_release_url(owner, repo)
    r = requests.get(api, timeout=timeout, headers={"User-Agent": "TibiaToolsApp"})
    if r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code}")
    data = r.json() if r.text else {}
    tag = str(data.get('tag_name') or data.get('name') or '').strip() or '?'
    html_url = str(data.get('html_url') or f'https://github.com/{owner}/{repo}/releases').strip()
    return GithubReleaseInfo(owner=owner, repo=repo, tag=tag, html_url=html_url)

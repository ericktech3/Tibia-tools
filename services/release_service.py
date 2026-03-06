from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from integrations.github_releases import GithubReleaseInfo, fetch_latest_release, parse_github_repo


class InvalidGithubRepoUrl(ValueError):
    """Raised when the configured repository URL is not a GitHub repository URL."""


class GithubReleaseLookupError(RuntimeError):
    """Raised when the latest GitHub release cannot be resolved."""


@dataclass(frozen=True)
class ReleaseCheckResult:
    owner: str
    repo: str
    tag: str
    html_url: str
    releases_url: str



def parse_repo_url(url: str) -> tuple[str, str]:
    parsed = parse_github_repo(url)
    if not parsed:
        raise InvalidGithubRepoUrl("URL do GitHub inválida.")
    return parsed



def build_releases_url(url: str) -> str:
    owner, repo = parse_repo_url(url)
    return f"https://github.com/{owner}/{repo}/releases"



def fetch_latest_release_for_repo_url(url: str, timeout: int = 15) -> ReleaseCheckResult:
    owner, repo = parse_repo_url(url)
    try:
        info = fetch_latest_release(owner, repo, timeout=timeout)
    except ValueError as exc:
        message = str(exc).strip()
        if message == "HTTP 404":
            raise GithubReleaseLookupError("Nenhuma release publicada ainda.") from exc
        raise GithubReleaseLookupError(f"Não consegui consultar as releases: {message}") from exc
    except Exception as exc:  # pragma: no cover - safety net for requests/network runtime differences
        raise GithubReleaseLookupError(f"Não consegui consultar as releases: {exc}") from exc

    return ReleaseCheckResult(
        owner=info.owner,
        repo=info.repo,
        tag=info.tag,
        html_url=info.html_url,
        releases_url=f"https://github.com/{info.owner}/{info.repo}/releases",
    )



def has_unseen_release(last_seen: Optional[str], latest_tag: str) -> bool:
    return bool((last_seen or "").strip() and (latest_tag or "").strip() and (last_seen or "").strip() != (latest_tag or "").strip())

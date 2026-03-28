"""Git operations for the legislation repo.

Wrapper over subprocess to control author, historical dates,
and commit trailers.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from legalize.models import CommitInfo
from legalize.committer.message import format_commit_message

logger = logging.getLogger(__name__)


class GitRepo:
    """Manages a Git repository for the legislation output."""

    def __init__(self, path: str | Path, committer_name: str, committer_email: str):
        self._path = Path(path)
        self._committer_name = committer_name
        self._committer_email = committer_email

    def _run(self, args: list[str], env: dict | None = None, check: bool = True) -> str:
        """Runs a git command and returns stdout."""
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        result = subprocess.run(
            ["git"] + args,
            cwd=self._path,
            capture_output=True,
            text=True,
            env=full_env,
        )

        if check and result.returncode != 0:
            logger.error("git %s failed: %s", " ".join(args), result.stderr)
            raise subprocess.CalledProcessError(
                result.returncode, ["git"] + args, result.stdout, result.stderr
            )

        return result.stdout.strip()

    def init(self) -> None:
        """Initializes the git repo if it does not exist."""
        self._path.mkdir(parents=True, exist_ok=True)

        if not (self._path / ".git").exists():
            self._run(["init"])
            self._run(["config", "user.name", self._committer_name])
            self._run(["config", "user.email", self._committer_email])
            logger.info("Repo initialized at %s", self._path)

    def write_and_add(self, rel_path: str, content: str) -> bool:
        """Writes a file and adds it to the staging area.

        Args:
            rel_path: Relative path within the repo.
            content: Content to write.

        Returns:
            True if the file changed compared to the last commit.
        """
        file_path = self._path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if content changed
        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            if existing == content:
                return False

        file_path.write_text(content, encoding="utf-8")
        self._run(["add", rel_path])
        return True

    def commit(self, info: CommitInfo) -> str | None:
        """Creates a commit with the CommitInfo data.

        Sets GIT_AUTHOR_DATE to the historical BOE date
        and GIT_COMMITTER_DATE to the same date.

        Args:
            info: Commit data.

        Returns:
            SHA of the created commit, or None if there were no changes.
        """
        # Verify there are staged changes
        status = self._run(["status", "--porcelain"])
        if not status:
            logger.debug("Nothing to commit")
            return None

        message = format_commit_message(info)
        # Git does not accept pre-1970 dates (Unix epoch)
        from datetime import date as date_type
        git_date = info.author_date
        if git_date < date_type(1970, 1, 2):
            git_date = date_type(1970, 1, 2)
        author_date = f"{git_date.isoformat()}T00:00:00"

        env = {
            "GIT_AUTHOR_DATE": author_date,
            "GIT_COMMITTER_DATE": author_date,
            "GIT_AUTHOR_NAME": info.author_name,
            "GIT_AUTHOR_EMAIL": info.author_email,
        }

        self._run(["commit", "-m", message], env=env)

        sha = self._run(["rev-parse", "HEAD"])
        logger.info("Commit created: %s — %s", sha[:8], info.subject)

        # Update in-memory idempotency cache
        if hasattr(self, "_existing_commits"):
            source_id = info.trailers.get("Source-Id", "")
            norm_id = info.trailers.get("Norm-Id", "")
            if source_id and norm_id:
                self._existing_commits.add((source_id, norm_id))

        return sha

    def load_existing_commits(self) -> None:
        """Loads all existing Source-Id+Norm-Id pairs into memory.

        A single git log at startup, then lookups are O(1).
        """
        self._existing_commits: set[tuple[str, str]] = set()
        try:
            output = self._run(
                ["log", "--all", "--format=%B%x00"],
                check=False,
            )
            if not output.strip():
                return

            for body in output.split("\0"):
                source_id = ""
                norm_id = ""
                for line in body.splitlines():
                    if line.startswith("Source-Id: "):
                        source_id = line[len("Source-Id: "):]
                    elif line.startswith("Norm-Id: "):
                        norm_id = line[len("Norm-Id: "):]
                if source_id and norm_id:
                    self._existing_commits.add((source_id, norm_id))

            logger.debug("Loaded %d existing commits", len(self._existing_commits))
        except Exception:
            pass

    def has_commit_with_source_id(self, source_id: str, norm_id: str | None = None) -> bool:
        """Checks whether a commit with this Source-Id + Norm-Id already exists."""
        if not hasattr(self, "_existing_commits"):
            self.load_existing_commits()

        if norm_id is None:
            return any(s == source_id for s, _ in self._existing_commits)

        return (source_id, norm_id) in self._existing_commits

    def push(self, remote: str = "origin", branch: str = "main") -> None:
        """Push to the remote."""
        self._run(["push", remote, branch])
        logger.info("Push completed: %s/%s", remote, branch)

    def log(self, fmt: str = "%ai  %s", reverse: bool = True) -> str:
        """Returns the formatted log."""
        args = ["log", f"--format={fmt}"]
        if reverse:
            args.append("--reverse")
        return self._run(args, check=False)

    def diff(self, ref1: str, ref2: str, path: str | None = None) -> str:
        """Returns the diff between two refs."""
        args = ["diff", ref1, ref2]
        if path:
            args.extend(["--", path])
        return self._run(args, check=False)

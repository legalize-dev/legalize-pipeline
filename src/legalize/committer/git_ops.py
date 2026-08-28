"""Git operations for the legislation repo.

Wrapper over subprocess to control author, historical dates,
and commit trailers.

Includes FastImporter for bulk bootstrap (git fast-import),
which is 10-50x faster than per-commit git add/commit.
"""

from __future__ import annotations

import calendar
import logging
import os
import re
import subprocess
from datetime import date as date_type
from pathlib import Path, PurePosixPath

from legalize.models import CommitInfo
from legalize.committer.message import format_commit_message

logger = logging.getLogger(__name__)


# Env vars that the parent shell may have set to point at a different repo
# (e.g. when the pipeline runs from inside a git pre-commit / pre-push hook).
# We must strip them so subprocess git calls operate on ``cwd``, not on the
# parent context. Otherwise sandbox repos created by tests inherit the
# parent's hooks and trigger recursive pre-commit failures.
_GIT_ENV_VARS_TO_STRIP = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
)


def _clean_git_env(extra: dict | None = None) -> dict:
    """Build a subprocess env dict that ignores inherited git context."""
    env = os.environ.copy()
    for var in _GIT_ENV_VARS_TO_STRIP:
        env.pop(var, None)
    if extra:
        env.update(extra)
    return env


_PUBLISHED_ON = re.compile(r"^publication_date:\s*\"?(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def _published_on(markdown: str) -> str | None:
    """The publication date off a rendered norm's frontmatter."""
    match = _PUBLISHED_ON.search(markdown)
    return match.group(1) if match else None


def _is_another_act(existing: str, incoming: str) -> bool:
    """Whether these two documents are different acts sharing one identifier.

    A law keeps its publication date forever: a new version of the same law carries
    the date it was published, whatever changed in the body. Two documents under one
    file name with two publication dates are therefore two acts, and writing the
    second one destroys the first — which is how Portugal ended up with military
    promotions published under the file name of the portaria they shadowed. Both
    dates have to be readable for the check to fire, so a country that does not
    write one is left exactly as it was.
    """
    old, new = _published_on(existing), _published_on(incoming)
    return bool(old and new and old != new)


class GitRepo:
    """Manages a Git repository for the legislation output."""

    def __init__(self, path: str | Path, committer_name: str, committer_email: str):
        self._path = Path(path)
        self._committer_name = committer_name
        self._committer_email = committer_email
        # Files this run declined to overwrite because they hold a different act.
        # finalize_daily turns them into errors: a law that cannot be published
        # has to make the run red, not just leave a line in the log.
        self.refused: list[str] = []
        # Directories already visible in a sparse checkout. ``None`` until the
        # first write asks, because a normal clone must not pay for a git call.
        self._cones: set[str] | None = None
        self._sparse = False

    def _run(self, args: list[str], env: dict | None = None, check: bool = True) -> str:
        """Runs a git command and returns stdout.

        Uses :func:`_clean_git_env` to strip any inherited GIT_DIR /
        GIT_INDEX_FILE / GIT_WORK_TREE so the subprocess operates on
        ``cwd=self._path``. See module docstring for context.
        """
        full_env = _clean_git_env(env)

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
        self.ensure_visible(str(PurePosixPath(rel_path).parent))
        file_path = self._path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if content changed vs what's on disk
        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            if existing == content:
                return False  # unchanged — no need to stage
            if _is_another_act(existing, content):
                logger.error(
                    "%s already holds an act published on %s and this one is from %s: "
                    "two different acts resolve to the same identifier. Refusing to "
                    "overwrite — the published law stays, this one is not written. "
                    "The country's identifier rule needs a discriminator.",
                    rel_path,
                    _published_on(existing),
                    _published_on(content),
                )
                self.refused.append(rel_path)
                return False

        file_path.write_text(content, encoding="utf-8")
        self._run(["add", rel_path])
        return True

    def sync_index(self) -> None:
        """Rebuild the index from HEAD, so the next commit's tree comes from it.

        ``git fast-import`` moves the ref and never touches the index, and
        ``FastImporter`` only resets the working tree on its last chunk. Any
        plain ``git commit`` afterwards — the repo-meta commit is the one that
        runs in a ``finally`` — builds its tree from an index that predates the
        import, so the commit deletes every law fast-import just wrote.

        ``check=False``: a repo whose HEAD is still unborn has nothing to reset
        to, which is the normal state on the first commit of a bootstrap.
        """
        self._run(["reset", "--mixed", "-q", "HEAD"], check=False)

    def ensure_visible(self, directory: str) -> None:
        """Make ``directory`` visible when the checkout is sparse.

        CI clones a country repo sparsely: writing the 171,722 files of Portugal
        into the runner's working tree took 48 of the job's 55 allowed minutes,
        while the daily touches a handful of them. Outside the cone the file is
        invisible to ``git add`` and — worse — absent from disk, so
        ``write_and_add``'s unchanged-content check would read nothing and
        re-commit an identical law every morning. Public because a daily that
        *reads* the repo needs the same guarantee before it globs a directory.

        A full checkout has no sparse-checkout file and pays one ``git config``
        call per run.
        """
        if self._cones is None:
            sparse = self._run(["config", "--get", "core.sparseCheckout"], check=False)
            self._sparse = sparse.strip().lower() == "true"
            self._cones = set()
        if not self._sparse:
            return
        if directory in (".", "") or directory in self._cones:
            return
        self._run(["sparse-checkout", "add", directory])
        self._cones.add(directory)

    def commit(self, info: CommitInfo) -> str | None:
        """Creates a commit with the CommitInfo data.

        Sets GIT_AUTHOR_DATE to the historical BOE date
        and GIT_COMMITTER_DATE to the same date.

        Args:
            info: Commit data.

        Returns:
            SHA of the created commit, or None if there were no changes.
        """
        message = format_commit_message(info)
        # Git does not accept pre-1970 dates (Unix epoch)
        from datetime import date as date_type

        git_date = info.author_date
        if git_date < date_type(1970, 1, 2):
            git_date = date_type(1970, 1, 2)
        # Spelled with the offset, because git applies the machine's zone to a
        # naive timestamp and the day then depends on where the run happened.
        # A published corpus carries five commits at +01:00/+02:00 from exactly
        # this, two of which fall on the previous day in UTC — a Source-Date the
        # commit no longer agrees with (spec v0.4, §Dates). The bootstrap path
        # never had the bug: it pins "+0000" in _fast_import_commit below.
        author_date = f"{git_date.isoformat()}T00:00:00+00:00"

        env = {
            "GIT_AUTHOR_DATE": author_date,
            "GIT_COMMITTER_DATE": author_date,
            "GIT_AUTHOR_NAME": info.author_name,
            "GIT_AUTHOR_EMAIL": info.author_email,
            "GIT_COMMITTER_NAME": self._committer_name,
            "GIT_COMMITTER_EMAIL": self._committer_email,
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

    def load_existing_commits(self) -> set[tuple[str, str]]:
        """Loads all existing Source-Id+Norm-Id pairs into memory, and returns them.

        A single git log at startup, then lookups are O(1).
        Uses git's native trailer parsing for efficiency.

        It returns the set as well as storing it because it read as a getter to
        the one caller that did not use :meth:`has_commit_with_source_id`, which
        got ``None`` and asked whether a pair was ``in`` it — a TypeError, caught
        by a broad ``except`` and logged as "Error recording amendment on …" once
        per law, on the path that records what an act changed.
        """
        self._existing_commits: set[tuple[str, str]] = set()
        try:
            # Try native trailer format first (git 2.40+, much faster)
            output = self._run(
                [
                    "log",
                    "--all",
                    "--format=%(trailers:key=Source-Id,valueonly,separator=)%x09%(trailers:key=Norm-Id,valueonly,separator=)%x00",
                ],
                check=False,
            )
            if not output.strip():
                return self._existing_commits

            for entry in output.split("\0"):
                entry = entry.strip()
                if not entry or "\t" not in entry:
                    continue
                source_id, _, norm_id = entry.partition("\t")
                if source_id and norm_id:
                    self._existing_commits.add((source_id.strip(), norm_id.strip()))

            logger.debug("Loaded %d existing commits", len(self._existing_commits))
        except subprocess.CalledProcessError:
            logger.warning("Could not load existing commits", exc_info=True)
        return self._existing_commits

    def has_commit_with_source_id(self, source_id: str, norm_id: str | None = None) -> bool:
        """Checks whether a commit with this Source-Id + Norm-Id already exists."""
        if not hasattr(self, "_existing_commits"):
            self.load_existing_commits()

        if norm_id is None:
            return any(s == source_id for s, _ in self._existing_commits)

        return (source_id, norm_id) in self._existing_commits

    def push(self, remote: str = "origin", branch: str = "HEAD") -> None:
        """Push to the remote (defaults to current branch)."""
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


class FastImportDied(RuntimeError):
    """git fast-import is gone, so every later write fails the same way.

    Distinct from a per-law error on purpose: callers loop over hundreds of
    thousands of reforms inside ``except Exception`` and would otherwise log one
    traceback per remaining reform and still report a number at the end. The
    import is over the moment the pipe breaks; the run has to stop and say so.
    """


class FastImporter:
    """Bulk commit generator using git fast-import.

    10-50x faster than per-commit git add/commit for bootstrap.
    Streams commits directly to git fast-import via stdin pipe,
    so memory usage stays constant regardless of commit count.

    Additive on non-empty repos: if ``refs/heads/main`` already
    points somewhere, the first emitted commit anchors on that tip
    so the stream extends history instead of orphaning it. Assumes
    the caller is the exclusive writer to ``refs/heads/main`` for
    the duration of the session — concurrent pushes (e.g. a daily
    cron) racing the importer would silently lose their commits
    because the captured parent SHA goes stale.

    Usage:
        with FastImporter(repo_path, committer_name, committer_email) as fi:
            fi.commit(file_path, content, message, author_date, env_overrides)
            fi.commit(...)
        # On exit: closes stdin, waits for fast-import to finish, then checkout.
    """

    def __init__(
        self,
        path: str | Path,
        committer_name: str,
        committer_email: str,
        checkout: bool = True,
    ):
        # checkout=False for every session but the last of a chunked import:
        # _checkout is a `git reset --hard`, which materialises the whole tree,
        # and doing that once per chunk over 171,725 files costs more than the
        # import it follows.
        self._checkout_on_exit = checkout
        self._path = Path(path)
        self._committer_name = committer_name
        self._committer_email = committer_email
        self._proc: subprocess.Popen | None = None
        self._mark: int = 0
        self._commit_count: int = 0
        # Track current tree state: rel_path -> mark number
        self._tree: dict[str, int] = {}
        # Existing refs/heads/main tip captured at enter-time. When set, the
        # first emitted commit references it as its parent so we extend
        # history instead of producing an orphan that fast-import refuses to
        # fast-forward onto main.
        self._initial_parent: str | None = None

    def __enter__(self) -> FastImporter:
        self._ensure_repo()
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "refs/heads/main"],
            cwd=self._path,
            capture_output=True,
            check=False,
            env=_clean_git_env(),
        )
        if result.returncode == 0:
            self._initial_parent = result.stdout.decode().strip()
            logger.info(
                "FastImporter: extending refs/heads/main from %s",
                self._initial_parent[:12],
            )
        # --depth: 87 % of Portugal's 12.55 GiB pack was directory trees, not law
        # text. A flat directory of 157,504 files is one 8 MB tree object that every
        # commit rewrites, and fast-import cuts delta chains at depth 50, so every
        # 50th commit stores those 8 MB whole. Measured on a bench that reproduces
        # the shape (157,504 files, 20,000 commits, one file touched each):
        #
        #     depth  50 (default)  1,345.9 s   0.257 GiB   13.5 KiB/commit
        #     depth 500            1,312.6 s   0.036 GiB    1.9 KiB/commit
        #
        # Seven times smaller for the same import time — the cost is that reading a
        # long chain needs more hops. It scales with files per directory, so it pays
        # off everywhere: es has 12,000, lv 15,000, pt 157,504.
        self._proc = subprocess.Popen(
            ["git", "fast-import", "--quiet", "--depth=500"],
            cwd=self._path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=_clean_git_env(),
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._proc is None:
            return
        try:
            self._proc.stdin.close()
        except BrokenPipeError:
            # fast-import is already gone; closing our end must not mask the
            # FastImportDied that is on its way up.
            pass
        self._proc.wait()
        if exc_type is None and self._commit_count > 0:
            if self._proc.returncode != 0:
                # The ref did not move, so this chunk is not in the repo — and
                # the next chunk would anchor on the previous tip and carry on,
                # leaving a hole in the middle of the history that a rerun does
                # not backfill (_resume_index reads the tip and skips past it).
                # Logging it was worse than useless: stderr is not captured, so
                # the message was always empty and the run reported success.
                raise FastImportDied(
                    f"git fast-import exited {self._proc.returncode} after "
                    f"{self._commit_count} queued commits; refs/heads/main did not "
                    "move (its own error is on stderr, above)"
                )
            logger.info("git fast-import: %d commits imported", self._commit_count)
            if self._checkout_on_exit:
                self._checkout()

    @property
    def commit_count(self) -> int:
        return self._commit_count

    def _next_mark(self) -> int:
        self._mark += 1
        return self._mark

    def _date_to_epoch(self, d: date_type) -> int:
        if d < date_type(1970, 1, 2):
            d = date_type(1970, 1, 2)
        return calendar.timegm(d.timetuple())

    def _write(self, data: bytes) -> None:
        """Write data directly to git fast-import stdin."""
        try:
            self._proc.stdin.write(data)
        except BrokenPipeError as exc:
            raise FastImportDied(
                f"git fast-import died after {self._commit_count} commits "
                "(its own error is on stderr, above)"
            ) from exc

    def commit(
        self,
        rel_path: str,
        content: str,
        info: CommitInfo,
    ) -> None:
        """Stream a commit directly to git fast-import.

        Each commit builds on top of the previous one (linear history).
        """
        content_bytes = content.encode("utf-8")
        blob_mark = self._next_mark()
        commit_mark = self._next_mark()

        # Blob
        self._write(f"blob\nmark :{blob_mark}\ndata {len(content_bytes)}\n".encode())
        self._write(content_bytes)
        self._write(b"\n")

        # Update tree state
        self._tree[rel_path] = blob_mark

        # Commit
        message = format_commit_message(info)
        message_bytes = message.encode("utf-8")
        epoch = self._date_to_epoch(info.author_date)
        tz = "+0000"

        lines = [
            "commit refs/heads/main",
            f"mark :{commit_mark}",
            f"author {info.author_name} <{info.author_email}> {epoch} {tz}",
            f"committer {self._committer_name} <{self._committer_email}> {epoch} {tz}",
            f"data {len(message_bytes)}",
        ]
        self._write(("\n".join(lines) + "\n").encode())
        self._write(message_bytes)
        self._write(b"\n")

        # Reference parent. After the first commit we chain by mark; for the
        # first commit we anchor on the pre-existing branch tip when one
        # exists, so this stream extends history instead of orphaning it.
        if self._commit_count > 0:
            self._write(f"from :{commit_mark - 2}\n".encode())
        elif self._initial_parent is not None:
            self._write(f"from {self._initial_parent}\n".encode())

        # File modification
        self._write(f"M 100644 :{blob_mark} {rel_path}\n".encode())
        self._write(b"\n")

        self._commit_count += 1

    def _ensure_repo(self) -> None:
        """Ensure git repo exists."""
        self._path.mkdir(parents=True, exist_ok=True)
        git_dir = self._path / ".git"
        env = _clean_git_env()
        if not git_dir.exists():
            subprocess.run(
                ["git", "init"],
                cwd=self._path,
                capture_output=True,
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "config", "user.name", self._committer_name],
                cwd=self._path,
                capture_output=True,
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "config", "user.email", self._committer_email],
                cwd=self._path,
                capture_output=True,
                check=True,
                env=env,
            )
        # Set every time, not only at init: fast-import writes its deltas at
        # depth 500 (see FastImporter), but pack-objects enforces the configured
        # depth on the chains it reuses, so a push or a gc with the default 50
        # would break them apart and write the pack back out whole — the 12.55
        # GiB this is there to avoid. The config is what keeps the repo, the
        # push and the maintenance runs telling the same story.
        subprocess.run(
            ["git", "config", "pack.depth", "500"],
            cwd=self._path,
            capture_output=True,
            check=True,
            env=env,
        )

    def _checkout(self) -> None:
        """Sync index + working tree with the new main tip after fast-import.

        ``git fast-import`` advances refs but never touches the index or
        the working tree. A plain ``git checkout main`` is a no-op when
        HEAD already points to main, so we reset the whole tree state
        atomically — this works for both empty bootstraps and additive
        runs on top of an existing branch.

        ``reset --hard`` overwrites any uncommitted local changes in the
        working tree. FastImporter is meant for bootstrap workflows on
        otherwise-clean repos; do not run it on a checkout with WIP.
        """
        subprocess.run(
            ["git", "reset", "--hard", "refs/heads/main"],
            cwd=self._path,
            capture_output=True,
            check=True,
            env=_clean_git_env(),
        )

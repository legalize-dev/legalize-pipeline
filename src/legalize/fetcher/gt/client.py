from __future__ import annotations

from pathlib import Path

from legalize.fetcher.base import LegislativeClient


FIXTURES = Path("tests/fixtures/gt")


class GTFixtureClient(LegislativeClient):
    """Fixture-backed Guatemala client for initial upstream integration tests.

    This is intentionally local-only. It lets the country package satisfy the
    upstream LegislativeClient contract while live Congreso/DCA discovery is
    still being developed.
    """

    def __init__(self, fixtures_dir: Path = FIXTURES) -> None:
        self.fixtures_dir = fixtures_dir

    def get_text(self, norm_id: str) -> bytes:
        path = self._text_path_for_norm(norm_id)
        return path.read_bytes()

    def get_metadata(self, norm_id: str) -> bytes:
        return self.get_text(norm_id)

    def close(self) -> None:
        return None

    def _text_path_for_norm(self, norm_id: str) -> Path:
        mapping = {
            "decreto-57-2008": "sample-ordinary-law-laip-official.txt",
            "decreto-13-2013": "reform-decree-13-2013.txt",
        }

        if norm_id not in mapping:
            raise KeyError(
                f"No Guatemala fixture text registered for {norm_id}")

        path = self.fixtures_dir / mapping[norm_id]

        if not path.exists():
            raise FileNotFoundError(path)

        return path

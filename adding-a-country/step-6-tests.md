# Step 6: Write tests

> Step 6 of 9 · [index](README.md) · previous: [`step-5-daily.md`](step-5-daily.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

Create `tests/test_parser_{code}.py` with fixture data (and optionally `tests/test_daily_{code}.py`):

```python
import pytest
from legalize.fetcher.{code}.parser import MyTextParser, MyMetadataParser
from legalize.countries import get_text_parser, get_metadata_parser

# Save sample data from your source in tests/fixtures/

class TestParser:
    def test_parse_text(self):
        data = Path("tests/fixtures/sample_{code}.xml").read_bytes()
        parser = MyTextParser()
        blocks = parser.parse_text(data)
        assert len(blocks) > 0
        assert blocks[0].versions  # has at least one version

    def test_metadata(self):
        data = Path("tests/fixtures/sample_{code}_meta.xml").read_bytes()
        parser = MyMetadataParser()
        meta = parser.parse(data, "NORM-ID-123")
        assert meta.country == "xx"
        assert meta.identifier == "NORM-ID-123"

    def test_filesystem_safe_id(self):
        # Ensure no colons, spaces, or special chars
        meta = ...
        assert ":" not in meta.identifier
        assert " " not in meta.identifier

class TestCountryDispatch:
    def test_registry(self):
        parser = get_text_parser("xx")
        assert isinstance(parser, MyTextParser)
```


---

**Next → read [`step-7-quality-gate.md`](step-7-quality-gate.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.

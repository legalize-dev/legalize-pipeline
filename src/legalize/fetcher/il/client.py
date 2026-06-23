"""OData V4 Knesset client for Israel (il)."""

from __future__ import annotations

import io
import json
import logging
import re
import time
import unicodedata
from typing import Any

import pdfplumber

from legalize.fetcher.base import HttpClient

logger = logging.getLogger(__name__)

# Zero-width / BOM / bidirectional control characters that pollute Hebrew PDF text.
_ZERO_WIDTH = (
    "\ufeff"  # zero-width no-break space / BOM
    "\u200b"  # zero-width space
    "\u200c\u200d"  # ZWNJ / ZWJ
    "\u200e\u200f"  # LRM / RLM
    "\u202a\u202b\u202c\u202d\u202e"  # bidi embedding/override
)
_ZERO_WIDTH_RE = re.compile(f"[{_ZERO_WIDTH}]")
_SOFT_HYPHEN_RE = re.compile(r"\s*\u00ad\s*")


def clean_extracted_text(text: str) -> str:
    """Normalize text extracted from Hebrew PDF/DOC documents.

    Replaces the soft hyphen (used as a maqaf/hyphen across line breaks) with a real
    hyphen, drops zero-width/bidi control characters and other C0/C1 control codes
    (keeping newlines and tabs), and collapses runs of spaces. UTF-8 throughout.
    """
    if not text:
        return text
    text = _SOFT_HYPHEN_RE.sub("-", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = "".join(
        c for c in text if c in ("\n", "\t") or unicodedata.category(c) not in ("Cc", "Cf")
    )
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines())


# Document selection: a law must be rendered from its ENACTED text (published in Reshumot),
# never from the draft bill, which carries sponsors (יוזמים) and an explanatory memorandum
# (דברי הסבר). KNS_DocumentBill rows are tagged by GroupTypeDesc.
_BILL_GROUP_MARKER = "הצעת חוק"  # draft bill — always excluded
_ENACTED_GROUP_MARKERS = ("פרסום ברשומות", "תיקון טעות")  # published in the official gazette
_APPLICATION_RANK = {"PDF": 0, "DOCX": 1, "DOC": 2}


def _document_priority(doc: dict) -> tuple[int, int] | None:
    """Rank a KNS_DocumentBill row for enacted-text selection (lower = better).

    Returns ``None`` for documents that must not be used: draft bills (which contain the
    explanatory memorandum) and non-text formats (PIC/TIF images, PPT).
    """
    group = doc.get("GroupTypeDesc") or ""
    if _BILL_GROUP_MARKER in group:
        return None
    app_rank = _APPLICATION_RANK.get(doc.get("ApplicationDesc"))
    if app_rank is None:
        return None
    group_rank = 0 if any(m in group for m in _ENACTED_GROUP_MARKERS) else 1
    return (group_rank, app_rank)


# Common Hebrew words reversed for visual Hebrew detection
REVERSED_WORDS = {"קוח", "ףיעס", "קרפ", "תסנכ", "תנידמ", "לארשי"}
LOGICAL_WORDS = {"חוק", "סעיף", "פרק", "כנסת", "מדינה", "ישראל"}


def is_visual_hebrew(text: str) -> bool:
    """Detects if a string is stored in visual (reversed) Hebrew format."""
    words = text.split()
    rev_count = sum(1 for w in words if any(rw in w for rw in REVERSED_WORDS))
    log_count = sum(1 for w in words if any(lw in w for lw in LOGICAL_WORDS))
    return rev_count > log_count


def reverse_visual_line(line: str) -> str:
    """Decodes a visual Hebrew line by reversing it and restoring LTR segments."""
    rev = line[::-1]

    # Fix brackets and parentheses that got reversed
    bracket_map = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<"}

    chars = list(rev)
    for i, c in enumerate(chars):
        if c in bracket_map:
            chars[i] = bracket_map[c]

    restored_line = "".join(chars)

    # Restore standard LTR sequences (digits and Latin characters)
    pattern = re.compile(r"[a-zA-Z0-9.,:/%\-–+]+")
    final_chars = list(restored_line)
    for match in pattern.finditer(restored_line):
        start, end = match.span()
        segment = restored_line[start:end]
        final_chars[start:end] = list(segment[::-1])

    return "".join(final_chars)


def is_reblaze_content(content: bytes) -> bool:
    """Detects if the content is a Reblaze WAF challenge/block page."""
    if not content:
        return False
    try:
        text = content.decode("utf-8", errors="ignore")
        text_lower = text.lower()
        if "reblaze" in text_lower or "challenge" in text_lower or "incident id" in text_lower:
            return True
        # If we expect JSON or PDF but get HTML, it's a block page
        stripped = text.strip()
        if (
            stripped.startswith("<!DOCTYPE html>")
            or stripped.startswith("<html>")
            or stripped.startswith("<html ")
        ):
            return True
    except Exception:
        pass
    return False


class IsraelClient(HttpClient):
    """Client for Knesset OData V4 services."""

    @classmethod
    def create(cls, country_config: Any) -> IsraelClient:
        """Create from CountryConfig."""
        source = country_config.source or {}
        base_url = source.get("base_url", "https://knesset.gov.il/OdataV4/ParliamentInfo/")
        user_agent = source.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        request_timeout = source.get("request_timeout", 30)
        max_retries = source.get("max_retries", 5)
        requests_per_second = source.get("requests_per_second", 1.0)
        return cls(
            base_url=base_url,
            user_agent=user_agent,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )

    def __init__(
        self,
        *,
        base_url: str = "https://knesset.gov.il/OdataV4/ParliamentInfo/",
        user_agent: str = "Mozilla/5.0",
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 1.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            user_agent=user_agent,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )

    def _get_odata(self, path: str) -> bytes:
        """Fetch OData response with Reblaze challenge detection and retries."""
        url = f"{self._base_url}/{path.lstrip('/')}" if self._base_url else path

        # OData queries should always request JSON format
        if "?" in url:
            if "$format=json" not in url:
                url += "&$format=json"
        else:
            url += "?$format=json"

        for attempt in range(self._max_retries):
            try:
                resp_bytes = self._get(url)
                if is_reblaze_content(resp_bytes):
                    wait = 2**attempt
                    logger.warning(
                        "Reblaze block detected on %s. Backing off for %ds...", url, wait
                    )
                    time.sleep(wait)
                    continue
                return resp_bytes
            except Exception as e:
                if attempt == self._max_retries - 1:
                    raise
                wait = 2**attempt
                logger.warning("Request error on %s, retrying in %ds: %s", url, wait, e)
                time.sleep(wait)

        raise RuntimeError(f"Reblaze challenge or block page continuously returned for: {url}")

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata package for a law.

        Compiles law properties, names, classifications, ministries, and corrections.
        """
        # 1. Fetch main law
        law_data = json.loads(self._get_odata(f"KNS_IsraelLaw({norm_id})"))

        # 2. Fetch related names
        names_data = json.loads(
            self._get_odata(f"KNS_IsraelLawName?$filter=IsraelLawID eq {norm_id}")
        )

        # 3. Fetch related classifications
        class_data = json.loads(
            self._get_odata(f"KNS_IsraelLawClassificiation?$filter=IsraelLawID eq {norm_id}")
        )

        # 4. Fetch related ministries
        ministry_data = json.loads(
            self._get_odata(f"KNS_IsraelLawMinistry?$filter=IsraelLawID eq {norm_id}")
        )

        # 5. Fetch related corrections
        corrections_data = json.loads(
            self._get_odata(
                f"KNS_IsraelLawLawCorrections?$filter=IsraelLawID eq {norm_id}&$expand=KNS_LawCorrection"
            )
        )

        # 6. Fetch related bindings (substantive amendments)
        bindings_data = json.loads(
            self._get_odata(f"KNS_LawBinding?$filter=IsraelLawID eq {norm_id}")
        )

        package = {
            "law": law_data,
            "names": names_data.get("value", []),
            "classifications": class_data.get("value", []),
            "ministries": ministry_data.get("value", []),
            "corrections": corrections_data.get("value", []),
            "bindings": bindings_data.get("value", []),
        }

        return json.dumps(package, ensure_ascii=False).encode("utf-8")

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        """Resolves documents of the law, downloads them, and returns a text package."""
        metadata_bytes = meta_data if meta_data is not None else self.get_metadata(norm_id)
        metadata_pkg = json.loads(metadata_bytes.decode("utf-8"))

        bindings = metadata_pkg.get("bindings", [])

        # Find the original law binding (BindingTypeDesc == 'החוק המקורי')
        original_binding = None
        for b in bindings:
            if b.get("BindingTypeDesc") == "החוק המקורי":
                original_binding = b
                break

        # Fallback to the earliest LawID if 'החוק המקורי' not found
        if not original_binding and bindings:
            sorted_bindings = sorted(bindings, key=lambda x: x.get("LawID", 0))
            original_binding = sorted_bindings[0]

        original_bill_id = original_binding.get("LawID") if original_binding else norm_id

        # Resolve the original bill: its PublicationDate is the original version date and its
        # expanded KNS_DocumentBill rows are the document candidates.
        original_pub_date, original_docs = self._get_bill_with_docs(original_bill_id)
        original_text = self._download_and_extract_text(original_docs)

        # Amendment dates: KNS_LawCorrection carries a real PublicationDate per amending bill.
        # Build a {bill_id: date} map as a fallback when a bill's own date is missing.
        correction_dates = self._build_correction_date_map(metadata_pkg.get("corrections", []))

        # Get text + real effective date for each amending law (Case B timeline reconstruction).
        reforms_text = []
        for b in bindings:
            if b.get("BindingTypeDesc") == "מתקן":
                bill_id = b.get("LawID")
                if not bill_id:
                    continue
                try:
                    bill_date, b_docs = self._get_bill_with_docs(bill_id)
                    txt = self._download_and_extract_text(b_docs)
                    reform_date = bill_date or correction_dates.get(bill_id)
                    if txt:
                        reforms_text.append({"bill_id": bill_id, "text": txt, "date": reform_date})
                except Exception as e:
                    logger.warning("Error fetching documents for amending bill %s: %s", bill_id, e)

        # Original version date: prefer the law's PublicationDate, then the original bill's date.
        law = metadata_pkg.get("law", {})
        pub_date_str = law.get("PublicationDate") or original_pub_date or law.get("LastUpdatedDate")

        package = {
            "original_text": original_text,
            "reforms_text": reforms_text,
            "publication_date": pub_date_str,
        }

        return json.dumps(package, ensure_ascii=False).encode("utf-8")

    def _get_bill_with_docs(self, bill_id: Any) -> tuple[str | None, list[dict]]:
        """Fetch a bill's PublicationDate and its expanded document rows in one request."""
        try:
            data = json.loads(
                self._get_odata(f"KNS_Bill?$filter=Id eq {bill_id}&$expand=KNS_DocumentBill")
            )
        except Exception as e:
            logger.warning("Error fetching bill %s: %s", bill_id, e)
            return None, []
        rows = data.get("value", [])
        if not rows:
            return None, []
        bill = rows[0]
        return bill.get("PublicationDate"), bill.get("KNS_DocumentBill", []) or []

    @staticmethod
    def _build_correction_date_map(corrections: list[dict]) -> dict[Any, str]:
        """Map amending bill id -> earliest correction date (PublicationDate fallback)."""
        bill_dates: dict[Any, str] = {}
        for c in corrections:
            lc = c.get("KNS_LawCorrection") or {}
            bid = lc.get("BillID")
            if bid is None:
                continue
            d = lc.get("CommencementDate") or lc.get("PublicationDate") or lc.get("VoteDate")
            if d and (bid not in bill_dates or d < bill_dates[bid]):
                bill_dates[bid] = d
        return bill_dates

    def _download_and_extract_text(self, docs: list[dict]) -> str:
        """Download the enacted law document from the list and extract its text.

        Selects the Reshumot publication (enacted text) over other non-bill documents and
        skips draft bills entirely, so the explanatory memorandum is never rendered as law.
        """
        ranked = [(p, d) for d in docs if (p := _document_priority(d)) is not None]
        ranked.sort(key=lambda item: item[0])
        candidates = [d for _, d in ranked]
        for doc in candidates:
            file_path = doc.get("FilePath")
            if not file_path:
                continue
            # Correct path slashes and collapse double slashes
            url = file_path.replace("\\", "/")
            url = re.sub(r"(https?://)/+", r"\1", url)
            try:
                # File paths are on fs.knesset.gov.il; use _get to respect rate limit
                content = self._get(url)
                if is_reblaze_content(content):
                    logger.warning("Reblaze challenge page returned for file: %s", url)
                    continue

                # Extract text using pdfplumber
                if doc.get("ApplicationDesc") == "PDF":
                    with pdfplumber.open(io.BytesIO(content)) as pdf:
                        text_pages = []
                        for page in pdf.pages:
                            t = page.extract_text() or ""
                            if is_visual_hebrew(t):
                                reversed_lines = [
                                    reverse_visual_line(line) for line in t.splitlines()
                                ]
                                t = "\n".join(reversed_lines)
                            text_pages.append(t)
                        return clean_extracted_text("\n\n".join(text_pages))
                else:
                    # Old .doc or .docx: python-docx can only parse .docx easily.
                    # Fallback to plain text decoding or skipping if not supported
                    try:
                        from docx import Document

                        d = Document(io.BytesIO(content))
                        return clean_extracted_text("\n\n".join(p.text for p in d.paragraphs))
                    except Exception:
                        # Can decode as raw string just in case there is ASCII/UTF-8
                        pass
            except Exception as e:
                logger.warning("Error downloading/parsing document %s: %s", url, e)

        return ""

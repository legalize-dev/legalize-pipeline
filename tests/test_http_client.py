"""Tests for the HttpClient base class.

Covers: retry on 429/503, rate limiting, session setup, close.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from legalize.fetcher.base import HttpClient


class ConcreteHttpClient(HttpClient):
    """Minimal concrete subclass for testing."""

    def get_text(self, norm_id: str) -> bytes:
        return self._get(f"{self._base_url}/text/{norm_id}")

    def get_metadata(self, norm_id: str) -> bytes:
        return self._get(f"{self._base_url}/meta/{norm_id}")


class TestHttpClientInit:
    def test_creates_session_with_user_agent(self):
        client = ConcreteHttpClient(user_agent="test-bot/1.0")
        assert client._session.headers["User-Agent"] == "test-bot/1.0"
        client.close()

    def test_extra_headers_applied(self):
        client = ConcreteHttpClient(extra_headers={"Accept": "application/xml"})
        assert client._session.headers["Accept"] == "application/xml"
        client.close()

    def test_base_url_stripped(self):
        client = ConcreteHttpClient(base_url="https://api.example.com/")
        assert client._base_url == "https://api.example.com"
        client.close()

    def test_context_manager(self):
        with ConcreteHttpClient() as client:
            assert client._session is not None
        # After exit, session should be closed
        assert client._session is not None  # object exists but session is closed


class TestHttpClientRetry:
    def test_retries_on_429(self):
        client = ConcreteHttpClient(max_retries=3, requests_per_second=0)

        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.raise_for_status = MagicMock()

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.content = b"ok"
        mock_resp_ok.raise_for_status = MagicMock()

        client._session.request = MagicMock(side_effect=[mock_resp_429, mock_resp_ok])

        with patch("legalize.fetcher.base.time.sleep"):
            result = client._get("https://example.com/test")

        assert result == b"ok"
        assert client._session.request.call_count == 2
        client.close()

    def test_retries_on_503(self):
        client = ConcreteHttpClient(max_retries=3, requests_per_second=0)

        mock_resp_503 = MagicMock()
        mock_resp_503.status_code = 503

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.content = b"recovered"
        mock_resp_ok.raise_for_status = MagicMock()

        client._session.request = MagicMock(side_effect=[mock_resp_503, mock_resp_ok])

        with patch("legalize.fetcher.base.time.sleep"):
            result = client._get("https://example.com/test")

        assert result == b"recovered"
        client.close()

    def test_raises_after_max_retries(self):
        client = ConcreteHttpClient(max_retries=2, requests_per_second=0)

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        # On last attempt, raise_for_status is called → raises HTTPError
        def raise_on_last():
            raise requests.HTTPError("429 Too Many Requests")

        mock_resp.raise_for_status = raise_on_last
        client._session.request = MagicMock(return_value=mock_resp)

        with patch("legalize.fetcher.base.time.sleep"):
            with pytest.raises(requests.HTTPError):
                client._get("https://example.com/test")

        assert client._session.request.call_count == 2
        client.close()

    def test_retries_on_connection_error(self):
        client = ConcreteHttpClient(max_retries=3, requests_per_second=0)

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.content = b"ok"
        mock_resp_ok.raise_for_status = MagicMock()

        client._session.request = MagicMock(
            side_effect=[requests.ConnectionError("refused"), mock_resp_ok]
        )

        with patch("legalize.fetcher.base.time.sleep"):
            result = client._get("https://example.com/test")

        assert result == b"ok"
        client.close()

    def test_no_retry_on_404(self):
        """404 is not retryable — should raise immediately."""
        client = ConcreteHttpClient(max_retries=3, requests_per_second=0)

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status = MagicMock(side_effect=requests.HTTPError("404 Not Found"))

        client._session.request = MagicMock(return_value=mock_resp)

        with pytest.raises(requests.HTTPError):
            client._get("https://example.com/test")

        # Should NOT retry on 404
        assert client._session.request.call_count == 1
        client.close()


class TestHttpClientServerError:
    def test_logs_the_body_of_a_500(self, caplog):
        """A 500 that only ever shows up from CI is undiagnosable without its body."""
        client = ConcreteHttpClient(max_retries=3, requests_per_second=0)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = (
            "<!DOCTYPE HTML><html><head><style>html { margin: 0 }</style></head>"
            "<body><h1>Access denied</h1>\n<p>for this network</p></body></html>"
        )
        mock_resp.raise_for_status = MagicMock(side_effect=requests.HTTPError("500"))
        client._session.request = MagicMock(return_value=mock_resp)

        with caplog.at_level("WARNING"), pytest.raises(requests.HTTPError):
            client._get("https://example.com/test")

        assert "HTTP 500: Access denied for this network" in caplog.text
        assert client._session.request.call_count == 1  # 500 is still not retried
        client.close()


class TestRetryStatusCodesPerClient:
    def test_a_client_can_retry_a_500(self):
        """data.gov.lt (TARClient) answers an intermittent 500 that succeeds on repeat."""

        class Flaky(ConcreteHttpClient):
            _retry_status_codes = (*HttpClient._retry_status_codes, 500)

        client = Flaky(max_retries=3, requests_per_second=0)
        bad, good = MagicMock(), MagicMock()
        bad.status_code = 500
        good.status_code = 200
        good.content = b"ok"
        client._session.request = MagicMock(side_effect=[bad, good])

        with patch("legalize.fetcher.base.time.sleep"):
            assert client._get("https://example.com/test") == b"ok"
        assert client._session.request.call_count == 2
        client.close()

    def test_the_default_still_does_not_retry_a_500(self):
        assert 500 not in HttpClient._retry_status_codes


class TestHttpClientRateLimit:
    def test_rate_limit_enforced(self):
        """Rate limiter should sleep between requests."""
        client = ConcreteHttpClient(requests_per_second=10.0)  # 100ms between

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ok"
        mock_resp.raise_for_status = MagicMock()
        client._session.request = MagicMock(return_value=mock_resp)

        with patch("legalize.fetcher.base.time.sleep") as mock_sleep:
            with patch("legalize.fetcher.base.time.monotonic", side_effect=[0.0, 0.0, 0.05, 0.05]):
                client._get("https://example.com/1")
                client._get("https://example.com/2")

        # Second call should trigger a sleep because only 50ms elapsed
        assert mock_sleep.called
        client.close()

    def test_no_rate_limit_when_zero(self):
        """requests_per_second=0 disables rate limiting."""
        client = ConcreteHttpClient(requests_per_second=0)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ok"
        mock_resp.raise_for_status = MagicMock()
        client._session.request = MagicMock(return_value=mock_resp)

        with patch("legalize.fetcher.base.time.sleep") as mock_sleep:
            client._get("https://example.com/1")
            client._get("https://example.com/2")

        mock_sleep.assert_not_called()
        client.close()


class TestHttpClientClose:
    def test_close_closes_session(self):
        client = ConcreteHttpClient()
        client._session.close = MagicMock()
        client.close()
        client._session.close.assert_called_once()


def test_lt_client_retries_a_500():
    from legalize.fetcher.lt.client import TARClient

    assert 500 in TARClient._retry_status_codes

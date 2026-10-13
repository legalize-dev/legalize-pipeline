"""The complete BOE index includes extraordinary Sunday editions and resumes safely."""

from datetime import date
from unittest.mock import MagicMock

from legalize.fetcher.es.discovery import diary_identifiers


def test_sunday_edition_survives_a_cached_resume(tmp_path):
    client = MagicMock()
    client.get_sumario.return_value = b'<response><status><code>200</code></status><data><seccion codigo="1"><item><identificador>BOE-A-2020-3693</identificador></item></seccion><seccion codigo="2"><item><identificador>OUTSIDE</identificador></item></seccion></data></response>'
    day = date(2020, 3, 15)
    assert day.weekday() == 6
    assert list(diary_identifiers(client, tmp_path, day, day)) == ["BOE-A-2020-3693"]
    client.get_sumario.reset_mock()
    assert list(diary_identifiers(client, tmp_path, day, day)) == ["BOE-A-2020-3693"]
    client.get_sumario.assert_not_called()


def test_legacy_summary_discovery_checks_sundays():
    from legalize.config import Config, CountryConfig
    from legalize.fetcher.es.catalogo import iter_norms_from_summaries

    client = MagicMock()
    client.get_sumario.return_value = b"<response><status><code>404</code></status></response>"
    day = date(2020, 3, 15)
    assert (
        list(iter_norms_from_summaries(client, Config(countries={"es": CountryConfig()}), day, day))
        == []
    )
    client.get_sumario.assert_called_once_with(day)

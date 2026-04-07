"""Discovery of Latvian legal acts via likumi.lv sitemaps.

likumi.lv publishes a sitemap index at /sitemap-index.xml that references
two sitemap files containing all individual law URLs:
- /sitemap-1.xml: ~50,000 URLs (12 MB)
- /sitemap-2.xml: ~26,208 URLs (6.4 MB)
Total: ~76,208 laws (validated 2026-04-07)

For daily updates, /ta/jaunakie/stajas-speka/{Y}/{M}/{D}/ returns plain HTML
listing laws that entered into force on a specific date.

robots.txt disallows ~483 specific law IDs (extracted into DISALLOWED_IDS).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date
from xml.etree import ElementTree as ET

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.lv.client import LikumiClient

logger = logging.getLogger(__name__)

# Sitemap XML namespace
_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Pattern to extract numeric ID and slug from likumi.lv URLs
# Examples: /ta/id/57980, /ta/id/57980-latvijas-republikas-satversme
_ID_PATTERN = re.compile(r"/ta/id/(\d+)")
_ID_SLUG_PATTERN = re.compile(r"/ta/id/(\d+)(?:-([^/?#]*))?")

# URL slug prefixes that indicate amendments or announcements (not consolidated laws).
# These documents use a non-TV HTML format and have no consolidated structure to parse.
# Skipping them dramatically reduces bootstrap size and time.
_SKIP_SLUG_PREFIXES: tuple[str, ...] = (
    "grozijumi-",  # "Grozījumi..." (amendments)
    "grozijums-",  # "Grozījums..." (singular amendment)
    "par-grozijumiem-",  # "Par grozījumiem..." (about amendments)
    "par-grozijumu-",  # "Par grozījumu..."
)

# IDs explicitly disallowed by robots.txt (483 entries, extracted 2026-04-07)
DISALLOWED_IDS: frozenset[int] = frozenset(
    {
        72,
        73,
        255,
        284,
        489,
        1219,
        1419,
        1420,
        1421,
        1958,
        2330,
        2331,
        2492,
        2705,
        2949,
        2950,
        2951,
        2994,
        3347,
        3481,
        3927,
        4174,
        4347,
        4581,
        5231,
        5284,
        5285,
        5633,
        5634,
        5782,
        6147,
        6686,
        6687,
        7095,
        7494,
        7823,
        8450,
        8451,
        8452,
        8540,
        8542,
        8949,
        8950,
        8951,
        8952,
        9497,
        9680,
        9861,
        10239,
        10240,
        10714,
        10957,
        10958,
        10959,
        11228,
        11740,
        11981,
        12420,
        12421,
        12828,
        13024,
        13227,
        13636,
        13637,
        13638,
        14074,
        14075,
        14076,
        14279,
        14742,
        15022,
        15023,
        15206,
        15307,
        15308,
        15536,
        15877,
        15878,
        15936,
        16051,
        16052,
        16235,
        16408,
        16566,
        17865,
        18056,
        18057,
        18214,
        18215,
        18216,
        18627,
        19073,
        19368,
        19842,
        20194,
        20195,
        20196,
        20527,
        20528,
        20529,
        20813,
        21529,
        21913,
        22095,
        22478,
        22479,
        22884,
        22885,
        23167,
        23415,
        23574,
        23793,
        23970,
        23971,
        24362,
        24363,
        24364,
        24742,
        24743,
        24744,
        25149,
        25150,
        25844,
        26335,
        26336,
        26337,
        26486,
        26487,
        27582,
        28128,
        32226,
        33449,
        33450,
        37068,
        37724,
        38216,
        39231,
        40045,
        40046,
        40254,
        40948,
        41303,
        41565,
        42031,
        42151,
        43002,
        43263,
        43480,
        44026,
        44369,
        44370,
        44610,
        44616,
        44717,
        45386,
        45387,
        45388,
        45689,
        45690,
        46177,
        46800,
        47156,
        47405,
        47683,
        47890,
        48040,
        48132,
        48260,
        48379,
        48762,
        48763,
        48764,
        49006,
        49007,
        49139,
        49193,
        49252,
        49440,
        49441,
        49581,
        49784,
        50074,
        50650,
        50964,
        51096,
        51097,
        51424,
        51425,
        51599,
        51850,
        51932,
        52971,
        52972,
        53247,
        53506,
        53651,
        54497,
        54498,
        55034,
        55035,
        55896,
        55897,
        55898,
        55899,
        56303,
        56492,
        56493,
        56767,
        57004,
        57798,
        58434,
        58586,
        58587,
        61974,
        61975,
        61976,
        61977,
        61978,
        61979,
        61980,
        61981,
        61982,
        62196,
        62590,
        62957,
        63264,
        63265,
        64399,
        64400,
        64573,
        64574,
        64750,
        64751,
        64938,
        65652,
        65653,
        66284,
        66285,
        66643,
        66860,
        67041,
        67266,
        67871,
        67872,
        68133,
        69646,
        69647,
        69648,
        69826,
        69827,
        69857,
        70862,
        71306,
        71649,
        72241,
        72242,
        72653,
        73231,
        73830,
        73831,
        74462,
        74950,
        75177,
        75453,
        75454,
        76244,
        76760,
        77112,
        77149,
        77319,
        77320,
        77449,
        77552,
        77731,
        77732,
        77913,
        78089,
        78100,
        78446,
        78665,
        79137,
        79138,
        79289,
        79766,
        79767,
        80342,
        80575,
        80576,
        81321,
        82229,
        82296,
        82297,
        82298,
        82594,
        82601,
        82602,
        84018,
        84019,
        84020,
        85341,
        85748,
        85749,
        86093,
        86486,
        86832,
        87156,
        87157,
        87584,
        88597,
        88598,
        88924,
        89178,
        90151,
        90603,
        90604,
        91239,
        91767,
        92093,
        92094,
        92552,
        93155,
        93457,
        93751,
        94477,
        94723,
        95081,
        95412,
        95636,
        95996,
        96364,
        96779,
        96860,
        97039,
        97291,
        98090,
        98091,
        98455,
        98759,
        99931,
        100400,
        100766,
        100873,
        100886,
        101250,
        101387,
        102413,
        102914,
        103734,
        103735,
        103978,
        104408,
        105430,
        105928,
        105929,
        107080,
        107574,
        107583,
        109100,
        109101,
        109102,
        110732,
        111199,
        112307,
        113064,
        113487,
        114696,
        115169,
        115535,
        116176,
        117823,
        118441,
        118984,
        122131,
        122708,
        124871,
        124879,
        126076,
        127274,
        128401,
        129497,
        131350,
        132540,
        133546,
        134408,
        134819,
        135957,
        138161,
        138373,
        139279,
        139280,
        140704,
        141570,
        141571,
        142381,
        143225,
        144288,
        144683,
        146646,
        147132,
        148134,
        149313,
        150850,
        152433,
        154442,
        155242,
        156406,
        157317,
        158109,
        158858,
        159650,
        160683,
        161680,
        161956,
        163899,
        163900,
        164947,
        167201,
        167561,
        170210,
        171745,
        173410,
        174336,
        175686,
        176791,
        177971,
        178757,
        179666,
        180765,
        181558,
        182431,
        183514,
        185451,
        186990,
        187849,
        189094,
        190540,
        191839,
        192356,
        194313,
        195373,
        196795,
        197149,
        197374,
        197511,
        197590,
        197594,
        197944,
        198099,
        198309,
        199554,
        200933,
        202282,
        203694,
        206132,
        208735,
        211397,
        213390,
        216025,
        217964,
        219584,
        221577,
        222945,
        225286,
        225727,
        225934,
        227718,
        229159,
        230323,
        231836,
        233062,
        234594,
        236681,
        238958,
        240989,
        241426,
        242947,
        245646,
        246466,
        248169,
        249118,
        249969,
        250763,
        251303,
    }
)


def extract_ids_from_sitemap(sitemap_xml: bytes) -> Iterator[str]:
    """Yield consolidated law IDs from a sitemap XML file.

    Each <url><loc> contains a URL like:
        https://likumi.lv/ta/id/194602-nodrosinajuma-valsts-agenturas-nolikums

    Skips:
    - IDs in robots.txt disallowed list
    - URLs whose slug starts with amendment prefixes (grozijumi-, grozijums-, par-grozijumiem-)
      because amendments use a different HTML format with no consolidated structure
    """
    root = ET.fromstring(sitemap_xml)
    for url_el in root.findall("sm:url/sm:loc", _SM_NS):
        url = url_el.text or ""
        match = _ID_SLUG_PATTERN.search(url)
        if not match:
            continue
        norm_id = int(match.group(1))
        slug = (match.group(2) or "").lower()
        if norm_id in DISALLOWED_IDS:
            continue
        if slug.startswith(_SKIP_SLUG_PREFIXES):
            continue
        yield str(norm_id)


def extract_sitemap_urls(index_xml: bytes) -> list[str]:
    """Extract sub-sitemap URLs from the sitemap index XML.

    Skips the top-level /sitemap.xml which only contains landing pages
    (not individual laws).
    """
    root = ET.fromstring(index_xml)
    urls = []
    for loc_el in root.findall("sm:sitemap/sm:loc", _SM_NS):
        url = loc_el.text or ""
        if url and not url.endswith("/sitemap.xml"):
            urls.append(url)
    return urls


class LikumiDiscovery(NormDiscovery):
    """Discovers Latvian legal acts via likumi.lv sitemaps.

    Bootstrap: 3 HTTP requests (sitemap-index + 2 sub-sitemaps) → ~76K IDs
    Daily: 1 HTTP request per day (jaunakie page)
    """

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all law IDs from likumi.lv sitemaps.

        Total: ~76,208 IDs across 2 sitemap files (excludes ~483 disallowed IDs).
        """
        assert isinstance(client, LikumiClient)

        index_xml = client.get_sitemap_index()
        sitemap_urls = extract_sitemap_urls(index_xml)
        logger.info("Discovered %d sub-sitemaps", len(sitemap_urls))

        seen: set[str] = set()
        for sitemap_url in sitemap_urls:
            sitemap_xml = client.get_sitemap(sitemap_url)
            count = 0
            for norm_id in extract_ids_from_sitemap(sitemap_xml):
                if norm_id in seen:
                    continue
                seen.add(norm_id)
                count += 1
                yield norm_id
            logger.info("Sitemap %s yielded %d IDs", sitemap_url, count)

        logger.info("Total unique IDs discovered: %d", len(seen))

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield IDs of laws that entered into force on target_date.

        Scrapes /ta/jaunakie/stajas-speka/{Y}/{M}/{D}/ which returns plain HTML
        with /ta/id/{N} links.
        """
        assert isinstance(client, LikumiClient)

        try:
            html_bytes = client.get_jaunakie_page(target_date)
        except Exception as exc:
            logger.warning("Failed to fetch jaunakie page for %s: %s", target_date, exc)
            return

        html_str = html_bytes.decode("utf-8", errors="replace")
        seen: set[str] = set()
        for match in _ID_PATTERN.finditer(html_str):
            norm_id_int = int(match.group(1))
            if norm_id_int in DISALLOWED_IDS:
                continue
            norm_id = str(norm_id_int)
            if norm_id in seen:
                continue
            seen.add(norm_id)
            yield norm_id

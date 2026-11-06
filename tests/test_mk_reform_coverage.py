import json
import subprocess

from scripts.check_mk_reform_coverage import missing_reforms

OLD_LAW = ("RM-1993-80-3349", "Закон за пензиското осигурување", "1993-12-30")
OLD_AMENDMENT = (
    "RM-1995-14-3958",
    "Закон за изменување на Законот за пензиското осигурување",
    "1995-03-14",
)
NEW_LAW = ("RM-2012-98-25996", "Закон за пензиското осигурување", "2012-08-01")
NEW_AMENDMENT = (
    "RM-2014-97-32407",
    "Закон за изменување на Законот за пензиското осигурување",
    "2014-06-26",
)
OTHER_AMENDMENT = (
    "RM-2014-1-1",
    "Закон за изменување на Законот за даночна постапка",
    "2014-01-01",
)
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _corpus(tmp_path, *files, commits=(), links=None):
    data = tmp_path / "data" / "json"
    data.mkdir(parents=True)
    for identifier, title, published, *version in files:
        metadata = {"identifier": identifier, "title": title, "publication_date": published}
        if version:
            metadata["extra"] = [["version", version[0]]]
        reforms = [{"source_id": act} for act in [identifier, *(links or {}).get(identifier, [])]]
        (data / f"{identifier}.json").write_text(
            json.dumps({"metadata": metadata, "reforms": reforms}), encoding="utf-8"
        )
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for source_id, norm_id in commits:
        message = f"reform\n\nSource-Id: {source_id}\nNorm-Id: {norm_id}\n"
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", message],
            check=True,
            env={**GIT_ENV, "HOME": str(tmp_path)},
        )
    return tmp_path / "data", repo


def test_amendment_is_owed_to_the_enactment_in_force_when_it_was_published(tmp_path):
    data, repo = _corpus(tmp_path, OLD_LAW, OLD_AMENDMENT, NEW_LAW, NEW_AMENDMENT)

    assert missing_reforms(data, repo) == [
        ("RM-1995-14-3958", "RM-1993-80-3349"),
        ("RM-2014-97-32407", "RM-2012-98-25996"),
    ]


def test_a_consolidated_text_takes_no_amendment_from_its_law(tmp_path):
    # LDBIS lists the 2013 consolidation of the 2012 pension law under the law's own title, and
    # a consolidation enacts nothing, so a later amendment is still owed to the 2012 law.
    consolidated = ("RM-2013-53-28096", NEW_LAW[1], "2013-04-11", "Пречистена верзија")
    data, repo = _corpus(
        tmp_path,
        NEW_LAW,
        consolidated,
        NEW_AMENDMENT,
        commits=[("RM-2014-97-32407", "RM-2012-98-25996")],
    )

    assert missing_reforms(data, repo) == []


def test_committed_pairs_and_laws_outside_the_repository_pass(tmp_path):
    data, repo = _corpus(
        tmp_path,
        NEW_LAW,
        NEW_AMENDMENT,
        OTHER_AMENDMENT,
        commits=[("RM-2014-97-32407", "RM-2012-98-25996")],
    )

    assert missing_reforms(data, repo) == []


def test_a_correction_is_owed_to_the_law_it_corrects(tmp_path):
    correction = ("RM-2014-99-32500", "Исправка на Законот за пензиското осигурување", "2014-07-01")
    amendment_correction = (
        "RM-2014-100-32501",
        "Исправка на Законот за изменување на Законот за пензиското осигурување",
        "2014-07-02",
    )
    data, repo = _corpus(tmp_path, NEW_LAW, correction, amendment_correction)

    assert missing_reforms(data, repo) == [
        ("RM-2014-100-32501", "RM-2012-98-25996"),
        ("RM-2014-99-32500", "RM-2012-98-25996"),
    ]


def test_an_act_the_laws_card_links_must_be_a_commit_even_when_its_title_names_no_law(tmp_path):
    # An amending act whose title is not "Закон за изменување ..." is reached only by the links.
    linked = ("RM-2015-1-2", "Закон за ратификација на Протоколот", "2015-01-01")
    data, repo = _corpus(
        tmp_path,
        NEW_LAW,
        linked,
        links={NEW_LAW[0]: [linked[0], "RM-2016-9-9"]},
    )

    # RM-2016-9-9 is linked but not in the repository, so it is owed nowhere.
    assert missing_reforms(data, repo) == [("RM-2015-1-2", "RM-2012-98-25996")]

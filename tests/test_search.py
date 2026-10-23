import pytest

from app.extensions import db
from app.models import Business
from app.services.search import query_key, search_key


@pytest.mark.parametrize(
    "typed,stored",
    [
        ("ezo", "ეზო"),
        ("EZO", "სასტუმრო ეზო"),
        ("khinkali", "ხინკალი"),
        ("xinkali", "ხინკალი"),
        ("tsentri", "ცენტრი"),
        ("centri", "ცენტრი"),
        ("qava", "ყავა"),
        ("kava", "ყავა"),
        ("shota", "შოთა"),
        ("chavchavadze", "ჭავჭავაძე"),
        ("gagarina", "Улица Гагарина"),
        ("coffee", "Coffee Lab"),
        ("cofe", "Coffee Lab"),
        ("ეზო", "Ezo"),
        ("o'neil", "ONeil"),
    ],
)
def test_spellings_match(typed, stored):
    assert query_key(typed) in search_key(stored)


@pytest.mark.parametrize(
    "typed,stored",
    [("chavchavadze", "ჭავჭავაძის გამზირი"), ("tbilisi", "თბილისში"), ("sastumro", "სასტუმროს")],
)
def test_dictionary_form_finds_case_forms(typed, stored):
    assert query_key(typed) in search_key(stored)


@pytest.mark.parametrize("typed,stored", [("ezo", "ზოო"), ("salon", "ბარი")])
def test_different_words_dont_match(typed, stored):
    assert search_key(typed) not in search_key(stored)


@pytest.fixture
def leads(app):
    rows = [
        Business(place_id="a", name="სასტუმრო ეზო", phone="+995 555 40 20 60", category="სასტუმრო",
                 address="Улица Гагарина 1, თბილისი"),
        Business(place_id="b", name="Nail Studio", phone="+995 32 2 11 22 33", whatsapp="+995 599 12 34 56",
                 category="ფრჩხილების სალონი", email="hello@nailstudio.ge"),
        Business(place_id="c", name="ბარი", phone=None, category="ბარი", address="ჭავჭავაძის გამზირი 5"),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


def names(client, **params):
    return sorted(b["name"] for b in client.get("/api/businesses", query_string=params).get_json()["items"])


@pytest.mark.parametrize("q", ["555402060", "555 40 20 60", "+995555402060", "555-40-20-60", "402060", "(555) 40 20 60"])
def test_phone_search_ignores_formatting(client, leads, q):
    assert names(client, q=q) == ["სასტუმრო ეზო"]


def test_whatsapp_number_is_searched(client, leads):
    assert names(client, q="599123456") == ["Nail Studio"]


def test_latin_finds_georgian_and_back(client, leads):
    assert names(client, q="ezo") == ["სასტუმრო ეზო"]
    assert names(client, q="sastumro ezo") == ["სასტუმრო ეზო"]
    assert names(client, q="ezo nail") == []  # every word must match
    assert names(client, q="ნაილ") == ["Nail Studio"]
    assert names(client, q="chavchavadze") == ["ბარი"]
    assert names(client, q="gagarina") == ["სასტუმრო ეზო"]
    assert names(client, q="nailstudio.ge") == ["Nail Studio"]
    assert names(client, q="   ") == ["Nail Studio", "ბარი", "სასტუმრო ეზო"]


def test_category_filter_is_forgiving(client, leads):
    assert names(client, category="salon") == ["Nail Studio"]
    assert names(client, category="სალონი") == ["Nail Studio"]

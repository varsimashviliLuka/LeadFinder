"""Forgiving text search: Georgian/Russian or Latin spelling, any phone formatting.

Both the stored text and what you type are reduced to the same loose "search key":
Georgian and Cyrillic letters become Latin, and spellings people mix up are merged
(ქ/კ/ყ are all k or q, ხ is kh or x, ც/წ/ჩ/ჭ are ts, c, ch or w...). So "ezo" finds
"ეზო", "khinkali" and "xinkali" find "ხინკალი", and "ეზო" finds "Ezo".
"""

import re

GEORGIAN = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z", "თ": "t", "ი": "i",
    "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o", "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s",
    "ტ": "t", "უ": "u", "ფ": "p", "ქ": "k", "ღ": "gh", "ყ": "q", "შ": "sh", "ჩ": "ch", "ც": "ts",
    "ძ": "dz", "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
}
CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "iu", "я": "ia",
}
TRANSLITERATION = str.maketrans({**GEORGIAN, **CYRILLIC})

# Applied in order, after transliteration. Each maps alternative spellings to one form.
LOOSE_SPELLINGS = (
    ("tch", "c"), ("kh", "x"), ("gh", "g"), ("zh", "j"), ("sh", "s"), ("ch", "c"), ("ts", "c"),
    ("tz", "c"), ("dz", "z"), ("ph", "p"), ("th", "t"), ("q", "k"), ("w", "c"), ("y", "i"), ("f", "p"),
)
NOT_LETTER_OR_DIGIT = re.compile(r"[^0-9a-z]+")
REPEATED = re.compile(r"(.)\1+")
MIN_PHONE_DIGITS = 3


def search_key(text):
    """Loose form of text for matching; '' for empty input."""
    if not text:
        return ""
    key = str(text).lower().translate(TRANSLITERATION)
    key = NOT_LETTER_OR_DIGIT.sub("", key)
    for spelling, replacement in LOOSE_SPELLINGS:
        key = key.replace(spelling, replacement)
    return REPEATED.sub(r"\1", key)


def query_key(word):
    """search_key for a typed word. Longer words drop a final vowel, so the dictionary
    form also finds Georgian case forms: chavchavadze → ჭავჭავაძის, tbilisi → თბილისში."""
    key = search_key(word)
    return key[:-1] if len(key) >= 5 and key[-1] in "aeiou" else key


def digits(text):
    return re.sub(r"\D", "", str(text)) if text else ""


def register_sqlite_functions(dbapi_connection, _record=None):
    """Make search_key() and digits() callable in SQL queries."""
    dbapi_connection.create_function("search_key", 1, search_key, deterministic=True)
    dbapi_connection.create_function("digits", 1, digits, deterministic=True)

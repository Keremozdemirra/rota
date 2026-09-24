"""Reading what a person types: CN codes and country names.

Nothing here touches the network or the data files, so every rule can be
tested on its own.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Separators people use when they write a CN code: "7208 51 20", "7208.51.20",
# "7208-51-20", and the no-break or thin spaces that EU documents put there.
_SEPARATORS = re.compile(r"[\s.\-   ]+")
_PREFIX = re.compile(r"^(?:cn|hs|taric)\s*:?\s*", re.IGNORECASE)
_EX = re.compile(r"^ex\s*(?=[0-9])", re.IGNORECASE)
_ASCII_DIGITS = re.compile(r"[0-9]+")


class InputError(ValueError):
    """A question the tool cannot read, e.g. a CN code with letters in it."""


def normalize_cn(value) -> tuple[str, list[str]]:
    """Digits of a CN (2 to 8 digits) or TARIC (10 digits) code, and warnings.

    Accepts "7208 51 20", "72085120", "7208.51.20", "ex 2507 00 80", and a
    heading or chapter prefix such as "7208" or "72". Only ASCII digits count:
    `str.isdigit` would also accept Arabic-Indic or superscript digits.
    """
    if isinstance(value, bool) or value is None:
        raise InputError("cn_code must be a string such as '7208 51 20'")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        raise InputError("cn_code must be a string such as '7208 51 20'")
    text = unicodedata.normalize("NFKC", value).strip()
    warnings: list[str] = []
    text = _PREFIX.sub("", text)
    if _EX.match(text):
        text = _EX.sub("", text)
        warnings.append("'ex' in the question was ignored; the answer says whether an 'ex' entry applies")
    digits = _SEPARATORS.sub("", text)
    if not digits:
        raise InputError("cn_code is empty")
    if not _ASCII_DIGITS.fullmatch(digits):
        raise InputError(f"cn_code must contain only digits and separators, got {value!r}"[:200])
    if len(digits) < 2 or len(digits) > 10:
        raise InputError(f"cn_code must have 2 to 10 digits (CN: 2, 4, 6 or 8; TARIC: 10), got {len(digits)}")
    if len(digits) % 2:
        warnings.append(f"{len(digits)} digits is not a CN level (2, 4, 6, 8; TARIC 10); read as a prefix")
    return digits, warnings


def format_cn(digits: str) -> str:
    """"72085120" -> "7208 51 20", the way the Official Journal writes codes."""
    if len(digits) <= 4:
        return digits
    rest = digits[4:]
    return " ".join([digits[:4]] + [rest[i:i + 2] for i in range(0, len(rest), 2)])


def cn_candidates(digits: str) -> list[str]:
    """Notations under which the CN may list a code.

    A heading without HS subheadings appears in the CN as "7221 00" or
    "2716 00 00", never as "7221" or "2716", so a 4-digit question is also
    looked up with zeros added.
    """
    out = [digits]
    if len(digits) == 4:
        out += [digits + "00", digits + "0000"]
    elif len(digits) == 6:
        out.append(digits + "00")
    return out


# ------------------------------------------------------------------ countries

# ISO 3166-1 alpha-2 codes for the country names used in the default-value
# tables, so that "IN" or "TR" can be typed. This is an input convenience of
# this tool: the tables themselves name countries, never codes.
ISO_BY_TABLE_NAME = {
    "Albania": "AL", "Algeria": "DZ", "Angola": "AO", "Argentina": "AR", "Armenia": "AM",
    "Australia": "AU", "Azerbaijan": "AZ", "Bahrain": "BH", "Bangladesh": "BD", "Belarus": "BY",
    "Benin": "BJ", "Bolivia": "BO", "Bosnia and Herzegovina": "BA", "Brazil": "BR", "Brunei": "BN",
    "Cambodia": "KH", "Cameroon": "CM", "Canada": "CA", "Chile": "CL", "China": "CN",
    "Colombia": "CO", "Congo": "CG", "Congo, Democratic Republic of": "CD", "Costa Rica": "CR",
    "Cuba": "CU", "Curaçao": "CW", "Dominican Republic": "DO", "Ecuador": "EC", "Egypt": "EG",
    "El Salvador": "SV", "Equatorial Guinea": "GQ", "Eritrea": "ER", "Eswatini": "SZ",
    "Ethiopia": "ET", "Gabon": "GA", "Georgia": "GE", "Ghana": "GH", "Guatemala": "GT",
    "Haiti": "HT", "Honduras": "HN", "Hong Kong": "HK", "India": "IN", "Indonesia": "ID",
    "Iran, Islamic Republic of": "IR", "Iraq": "IQ", "Israel": "IL", "Ivory Coast": "CI",
    "Jamaica": "JM", "Japan": "JP", "Jordan": "JO", "Kazakhstan": "KZ", "Kenya": "KE",
    "Korea, Republic of (South Korea)": "KR", "Kuwait": "KW", "Kyrgyzstan": "KG", "Laos": "LA",
    "Lebanon": "LB", "Liberia": "LR", "Libya": "LY", "Madagascar": "MG", "Malaysia": "MY",
    "Mali": "ML", "Mauritania": "MR", "Mauritius": "MU", "Mexico": "MX",
    "Moldova, Republic of": "MD", "Mongolia": "MN", "Montenegro": "ME", "Morocco": "MA",
    "Mozambique": "MZ", "Myanmar": "MM", "Namibia": "NA", "Nepal": "NP",
    "New Caledonia and dependencies": "NC", "New Zealand": "NZ", "Nicaragua": "NI", "Niger": "NE",
    "Nigeria": "NG", "North Korea (Democratic People's Republic of Korea)": "KP",
    "North Macedonia": "MK", "Oman": "OM", "Pakistan": "PK", "Panama": "PA",
    "Papua New Guinea": "PG", "Paraguay": "PY", "Peru": "PE", "Philippines": "PH", "Qatar": "QA",
    "Russian Federation": "RU", "Rwanda": "RW", "Saudi Arabia": "SA", "Senegal": "SN",
    "Serbia": "RS", "Sierra Leone": "SL", "Singapore": "SG", "South Africa": "ZA",
    "Sri Lanka": "LK", "Sudan": "SD", "Suriname": "SR", "Syria": "SY", "Taiwan": "TW",
    "Tajikistan": "TJ", "Tanzania, United Republic of": "TZ", "Thailand": "TH", "Togo": "TG",
    "Trinidad and Tobago": "TT", "Tunisia": "TN", "Türkiye": "TR", "Turkmenistan": "TM",
    "Uganda": "UG", "Ukraine": "UA", "United Arab Emirates": "AE", "United Kingdom": "GB",
    "United States": "US", "Uruguay": "UY", "Uzbekistan": "UZ", "Venezuela": "VE",
    "Viet Nam": "VN", "Yemen": "YE", "Zambia": "ZM", "Zimbabwe": "ZW",
}

# Other names for the same countries, from the English labels of the EU country
# authority table (EU Vocabularies, http://publications.europa.eu/resource/authority/country,
# read through the CELLAR SPARQL endpoint on 2026-09-24), leaving out demonyms and former
# states. Keys are matched after country_key(), so case, accents and apostrophes do not matter.
AUTHORITY_ALIASES = {
    "People’s Republic of China": "China",
    "Republic of Korea": "Korea, Republic of (South Korea)", "South Korea": "Korea, Republic of (South Korea)",
    "ROK": "Korea, Republic of (South Korea)",
    "Democratic People’s Republic of Korea": "North Korea (Democratic People's Republic of Korea)",
    "North Korea": "North Korea (Democratic People's Republic of Korea)",
    "DPRK": "North Korea (Democratic People's Republic of Korea)",
    "United Kingdom of Great Britain and Northern Ireland": "United Kingdom", "UK": "United Kingdom",
    "United States of America": "United States", "US": "United States", "USA": "United States",
    "Turkey": "Türkiye", "Republic of Türkiye": "Türkiye", "Republic of Turkey": "Türkiye",
    "Democratic Republic of the Congo": "Congo, Democratic Republic of",
    "Congo-Kinshasa": "Congo, Democratic Republic of",
    "Republic of the Congo": "Congo", "Congo-Brazzaville": "Congo",
    "Côte d’Ivoire": "Ivory Coast", "Republic of Côte d’Ivoire": "Ivory Coast",
    "Iran": "Iran, Islamic Republic of", "Islamic Republic of Iran": "Iran, Islamic Republic of",
    "Moldova": "Moldova, Republic of", "Republic of Moldova": "Moldova, Republic of",
    "Russia": "Russian Federation", "Syrian Arab Republic": "Syria",
    "Tanzania": "Tanzania, United Republic of", "United Republic of Tanzania": "Tanzania, United Republic of",
    "Vietnam": "Viet Nam", "Socialist Republic of Viet Nam": "Viet Nam",
    "Lao People’s Democratic Republic": "Laos", "Lao": "Laos",
    "Czech Republic": "Czechia", "Slovak Republic": "Slovakia", "Kingdom of the Netherlands": "Netherlands",
}
# This tool's own additions: common abbreviations and names that table does not list.
TOOL_ALIASES = {
    "PRC": "China", "S. Korea": "Korea, Republic of (South Korea)", "UAE": "United Arab Emirates",
    "DRC": "Congo, Democratic Republic of", "DR Congo": "Congo, Democratic Republic of",
    "Brunei Darussalam": "Brunei", "Swaziland": "Eswatini", "New Caledonia": "New Caledonia and dependencies",
}
# Asking for the fallback table by name: the only way to get its values for a country
# the tables do not list (Annex I rule quoted in legal.RULE_NOT_LISTED).
OTHER_ALIASES = {"Other": "Other Countries and Territories", "Other countries": "Other Countries and Territories",
                 "Other countries and territories": "Other Countries and Territories"}


def country_key(text: str) -> str:
    """Case-, accent- and punctuation-insensitive form of a country name."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = re.sub(r"[,.()]", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def resolve_country(value, table_names, extra: dict | None = None) -> tuple[str | None, list[str]]:
    """Table name for what was typed, or (None, suggestions).

    `table_names` are the names in the bundled tables; `extra` maps further
    names (EU Member States, Annex III countries) to a label of their own.
    """
    if not isinstance(value, str) or not value.strip():
        raise InputError("country must be a non-empty string, e.g. 'India' or 'IN'")
    if len(value) > 100:
        raise InputError("country name is longer than 100 characters")
    names = list(table_names) + list((extra or {}).keys())
    by_key = {country_key(n): n for n in names}
    raw = value.strip()
    key = country_key(raw)
    if key in by_key:
        return by_key[key], []
    if re.fullmatch(r"[A-Za-z]{2}", raw):
        code = raw.upper()
        for name, iso in ISO_BY_TABLE_NAME.items():
            if iso == code and name in table_names:
                return name, []
        for name, info in (extra or {}).items():
            if isinstance(info, dict) and info.get("iso") == code:
                return name, []
    for table in (AUTHORITY_ALIASES, TOOL_ALIASES, OTHER_ALIASES):
        alias = next((v for k, v in table.items() if country_key(k) == key), None)
        if alias and alias in names:
            return alias, []
    close = difflib.get_close_matches(key, list(by_key), n=3, cutoff=0.75)
    return None, [by_key[k] for k in close]

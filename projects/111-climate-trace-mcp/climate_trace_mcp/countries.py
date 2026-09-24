"""Country input: ISO 3166-1 codes and English names, resolved to what the API expects.

The Climate TRACE API takes a country as its ISO 3166-1 alpha-3 code (the
`gadmId` of a level-0 administrative area). People type "Germany", "DE" or
"deu"; this table turns those into "DEU" locally. Nothing typed by a person is
sent to the API: only a code taken from this table.

Sources (codes are facts; each checked 2026-09-24):
- ISO 3166-1 is maintained by the ISO 3166 Maintenance Agency,
  https://www.iso.org/iso-3166-country-codes.html. That page answered HTTP 403
  to this build's network, so the codes below were read from:
- UN Statistics Division, "Standard country or area codes for statistical use
  (M49)", https://unstats.un.org/unsd/methodology/m49/overview/, columns
  "ISO-alpha2 Code" and "ISO-alpha3 Code" (248 rows);
- Taiwan (TW, TWN), not listed in M49: EU Publications Office country authority
  table, https://publications.europa.eu/resource/authority/country/TWN
  (notations ISO_3166_1_ALPHA_2 = TW, ISO_3166_1_ALPHA_3 = TWN);
- XKX (Kosovo) and ZNC (Turkish Republic of Northern Cyprus) are not ISO 3166-1
  codes. Climate TRACE uses them ("Kosovo assigned ISO3 code XKX", "ZNC renamed
  'Turkish Republic of Northern Cyprus' at Level 0", https://climatetrace.org/terms)
  and lists them at https://api.climatetrace.org/v7/definitions/countries.
Display names are the ones that API list uses; the M49 name is kept where it
differs, so both resolve.
"""
from __future__ import annotations

import re

from .safety import clean, echo, fold

# alpha-2 | alpha-3 | name in the Climate TRACE API | UN M49 name where different
_TABLE = """\
AW|ABW|Aruba|
AF|AFG|Afghanistan|
AO|AGO|Angola|
AI|AIA|Anguilla|
AX|ALA|Åland Islands|
AL|ALB|Albania|
AD|AND|Andorra|
AE|ARE|United Arab Emirates|
AR|ARG|Argentina|
AM|ARM|Armenia|
AS|ASM|American Samoa|
AQ|ATA|Antarctica|
TF|ATF|French Southern Territories|
AG|ATG|Antigua and Barbuda|
AU|AUS|Australia|
AT|AUT|Austria|
AZ|AZE|Azerbaijan|
BI|BDI|Burundi|
BE|BEL|Belgium|
BJ|BEN|Benin|
BQ|BES|Bonaire, Sint Eustatius and Saba|
BF|BFA|Burkina Faso|
BD|BGD|Bangladesh|
BG|BGR|Bulgaria|
BH|BHR|Bahrain|
BS|BHS|Bahamas|
BA|BIH|Bosnia and Herzegovina|
BL|BLM|Saint Barthélemy|
BY|BLR|Belarus|
BZ|BLZ|Belize|
BM|BMU|Bermuda|
BO|BOL|Bolivia (Plurinational State of)|
BR|BRA|Brazil|
BB|BRB|Barbados|
BN|BRN|Brunei Darussalam|
BT|BTN|Bhutan|
BV|BVT|Bouvet Island|
BW|BWA|Botswana|
CF|CAF|Central African Republic|
CA|CAN|Canada|
CC|CCK|Cocos (Keeling) Islands|
CH|CHE|Switzerland|
CL|CHL|Chile|
CN|CHN|China|
CI|CIV|Côte d'Ivoire|Côte d’Ivoire
CM|CMR|Cameroon|
CD|COD|Democratic Republic of the Congo|
CG|COG|Congo|
CK|COK|Cook Islands|
CO|COL|Colombia|
KM|COM|Comoros|
CV|CPV|Cabo Verde|
CR|CRI|Costa Rica|
CU|CUB|Cuba|
CW|CUW|Curaçao|
CX|CXR|Christmas Island|
KY|CYM|Cayman Islands|
CY|CYP|Cyprus|
CZ|CZE|Czechia|
DE|DEU|Germany|
DJ|DJI|Djibouti|
DM|DMA|Dominica|
DK|DNK|Denmark|
DO|DOM|Dominican Republic|
DZ|DZA|Algeria|
EC|ECU|Ecuador|
EG|EGY|Egypt|
ER|ERI|Eritrea|
EH|ESH|Western Sahara|
ES|ESP|Spain|
EE|EST|Estonia|
ET|ETH|Ethiopia|
FI|FIN|Finland|
FJ|FJI|Fiji|
FK|FLK|Falkland Islands (Malvinas)|
FR|FRA|France|
FO|FRO|Faroe Islands|
FM|FSM|Micronesia (Federated States of)|
GA|GAB|Gabon|
GB|GBR|United Kingdom of Great Britain and Northern Ireland|
GE|GEO|Georgia|
GG|GGY|Guernsey|
GH|GHA|Ghana|
GI|GIB|Gibraltar|
GN|GIN|Guinea|
GP|GLP|Guadeloupe|
GM|GMB|Gambia|
GW|GNB|Guinea-Bissau|
GQ|GNQ|Equatorial Guinea|
GR|GRC|Greece|
GD|GRD|Grenada|
GL|GRL|Greenland|
GT|GTM|Guatemala|
GF|GUF|French Guiana|
GU|GUM|Guam|
GY|GUY|Guyana|
HK|HKG|China, Hong Kong Special Administrative Region|
HM|HMD|Heard Island and McDonald Islands|
HN|HND|Honduras|
HR|HRV|Croatia|
HT|HTI|Haiti|
HU|HUN|Hungary|
ID|IDN|Indonesia|
IM|IMN|Isle of Man|
IN|IND|India|
IO|IOT|British Indian Ocean Territory|
IE|IRL|Ireland|
IR|IRN|Iran (Islamic Republic of)|
IQ|IRQ|Iraq|
IS|ISL|Iceland|
IL|ISR|Israel|
IT|ITA|Italy|
JM|JAM|Jamaica|
JE|JEY|Jersey|
JO|JOR|Jordan|
JP|JPN|Japan|
KZ|KAZ|Kazakhstan|
KE|KEN|Kenya|
KG|KGZ|Kyrgyzstan|
KH|KHM|Cambodia|
KI|KIR|Kiribati|
KN|KNA|Saint Kitts and Nevis|
KR|KOR|Republic of Korea|
KW|KWT|Kuwait|
LA|LAO|Lao People's Democratic Republic|
LB|LBN|Lebanon|
LR|LBR|Liberia|
LY|LBY|Libya|
LC|LCA|Saint Lucia|
LI|LIE|Liechtenstein|
LK|LKA|Sri Lanka|
LS|LSO|Lesotho|
LT|LTU|Lithuania|
LU|LUX|Luxembourg|
LV|LVA|Latvia|
MO|MAC|China, Macao Special Administrative Region|
MF|MAF|Saint Martin (French Part)|
MA|MAR|Morocco|
MC|MCO|Monaco|
MD|MDA|Republic of Moldova|
MG|MDG|Madagascar|
MV|MDV|Maldives|
MX|MEX|Mexico|
MH|MHL|Marshall Islands|
MK|MKD|The former Yugoslav Republic of Macedonia|North Macedonia
ML|MLI|Mali|
MT|MLT|Malta|
MM|MMR|Myanmar|
ME|MNE|Montenegro|
MN|MNG|Mongolia|
MP|MNP|Northern Mariana Islands|
MZ|MOZ|Mozambique|
MR|MRT|Mauritania|
MS|MSR|Montserrat|
MQ|MTQ|Martinique|
MU|MUS|Mauritius|
MW|MWI|Malawi|
MY|MYS|Malaysia|
YT|MYT|Mayotte|
NA|NAM|Namibia|
NC|NCL|New Caledonia|
NE|NER|Niger|
NF|NFK|Norfolk Island|
NG|NGA|Nigeria|
NI|NIC|Nicaragua|
NU|NIU|Niue|
NL|NLD|Netherlands|Netherlands (Kingdom of the)
NO|NOR|Norway|
NP|NPL|Nepal|
NR|NRU|Nauru|Naoero
NZ|NZL|New Zealand|
OM|OMN|Oman|
PK|PAK|Pakistan|
PA|PAN|Panama|
PN|PCN|Pitcairn|
PE|PER|Peru|
PH|PHL|Philippines|
PW|PLW|Palau|
PG|PNG|Papua New Guinea|
PL|POL|Poland|
PR|PRI|Puerto Rico|
KP|PRK|Democratic People's Republic of Korea|
PT|PRT|Portugal|
PY|PRY|Paraguay|
PS|PSE|State of Palestine|
PF|PYF|French Polynesia|
QA|QAT|Qatar|
RE|REU|Réunion|
RO|ROU|Romania|
RU|RUS|Russian Federation|
RW|RWA|Rwanda|
SA|SAU|Saudi Arabia|
SD|SDN|Sudan|
SN|SEN|Senegal|
SG|SGP|Singapore|
GS|SGS|South Georgia and the South Sandwich Islands|
SH|SHN|Saint Helena|
SJ|SJM|Svalbard and Jan Mayen Islands|
SB|SLB|Solomon Islands|
SL|SLE|Sierra Leone|
SV|SLV|El Salvador|
SM|SMR|San Marino|
SO|SOM|Somalia|
PM|SPM|Saint Pierre and Miquelon|
RS|SRB|Serbia|
SS|SSD|South Sudan|
ST|STP|Sao Tome and Principe|
SR|SUR|Suriname|
SK|SVK|Slovakia|
SI|SVN|Slovenia|
SE|SWE|Sweden|
SZ|SWZ|Eswatini|
SX|SXM|Sint Maarten (Dutch part)|
SC|SYC|Seychelles|
SY|SYR|Syrian Arab Republic|
TC|TCA|Turks and Caicos Islands|
TD|TCD|Chad|
TG|TGO|Togo|
TH|THA|Thailand|
TJ|TJK|Tajikistan|
TK|TKL|Tokelau|
TM|TKM|Turkmenistan|
TL|TLS|Timor-Leste|
TO|TON|Tonga|
TT|TTO|Trinidad and Tobago|
TN|TUN|Tunisia|
TR|TUR|Turkey|Türkiye
TV|TUV|Tuvalu|
TW|TWN|Taiwan|
TZ|TZA|United Republic of Tanzania|
UG|UGA|Uganda|
UA|UKR|Ukraine|
UM|UMI|United States Minor Outlying Islands|
UY|URY|Uruguay|
US|USA|United States of America|
UZ|UZB|Uzbekistan|
VA|VAT|Holy See|
VC|VCT|Saint Vincent and the Grenadines|
VE|VEN|Venezuela (Bolivarian Republic of)|
VG|VGB|British Virgin Islands|
VI|VIR|United States Virgin Islands|
VN|VNM|Viet Nam|
VU|VUT|Vanuatu|
WF|WLF|Wallis and Futuna Islands|
WS|WSM|Samoa|
|XKX|Kosovo|
YE|YEM|Yemen|
ZA|ZAF|South Africa|
ZM|ZMB|Zambia|
|ZNC|Turkish Republic of Northern Cyprus|
ZW|ZWE|Zimbabwe|
"""

# Common English names that differ from both official names. The tool's own
# convenience list, not a standard; "Congo" alone stays the Republic of the
# Congo, as in ISO 3166-1 and M49.
_ALIASES = {
    "uk": "GBR", "united kingdom": "GBR", "great britain": "GBR", "britain": "GBR",
    "usa": "USA", "us": "USA", "united states": "USA",
    "russia": "RUS", "south korea": "KOR", "korea republic of": "KOR", "north korea": "PRK",
    "vietnam": "VNM", "turkiye": "TUR", "czech republic": "CZE", "holland": "NLD",
    "hong kong": "HKG", "macau": "MAC", "macao": "MAC",
    "syria": "SYR", "laos": "LAO", "moldova": "MDA", "tanzania": "TZA",
    "dr congo": "COD", "drc": "COD", "democratic republic of congo": "COD", "congo kinshasa": "COD",
    "republic of the congo": "COG", "republic of congo": "COG", "congo brazzaville": "COG",
    "ivory coast": "CIV", "cape verde": "CPV", "swaziland": "SWZ", "burma": "MMR", "brunei": "BRN",
    "palestine": "PSE", "vatican": "VAT", "vatican city": "VAT", "east timor": "TLS",
    "macedonia": "MKD", "uae": "ARE", "bosnia": "BIH", "northern cyprus": "ZNC",
}


class CountryError(ValueError):
    pass


def _key(name: str) -> str:
    s = fold(name).replace("&", " and ").replace(".", "").replace("'", "")
    s = re.sub(r"[^0-9a-z]+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    return re.sub(r"\bst\b", "saint", s)


def _build():
    by_a3, by_a2, index = {}, {}, {}

    def add(key, a3):
        if key and index.setdefault(key, a3) != a3:
            raise AssertionError("country name %r maps to %s and %s" % (key, index[key], a3))

    for line in _TABLE.splitlines():
        a2, a3, name, m49 = line.split("|")
        by_a3[a3] = name
        if a2:
            by_a2[a2] = a3
        for n in (name, m49):
            if n:
                add(_key(n), a3)
                add(_key(re.sub(r"\s*\([^)]*\)", "", n)), a3)
    for alias, a3 in _ALIASES.items():
        add(_key(alias), a3)
    return by_a3, by_a2, index


BY_ALPHA3, BY_ALPHA2, _INDEX = _build()


def name_of(alpha3: str) -> str | None:
    return BY_ALPHA3.get(alpha3)


def resolve(value) -> tuple:
    """(alpha-3, display name) for a code or English name, or CountryError."""
    if not isinstance(value, str):
        raise CountryError("country must be a string: an ISO 3166-1 alpha-3 code (DEU), alpha-2 (DE) or an English name")
    s = clean(value, 80)
    if not s:
        raise CountryError("country is empty")
    up = s.upper()
    if re.fullmatch(r"[A-Z]{3}", up) and up in BY_ALPHA3:
        return up, BY_ALPHA3[up]
    if re.fullmatch(r"[A-Z]{2}", up) and up in BY_ALPHA2:
        a3 = BY_ALPHA2[up]
        return a3, BY_ALPHA3[a3]
    key = _key(s)
    if key in _INDEX:
        a3 = _INDEX[key]
        return a3, BY_ALPHA3[a3]
    hints = sorted({BY_ALPHA3[a3] for k, a3 in _INDEX.items() if key and len(key) >= 3 and (key in k or k in key)})
    msg = "unknown country %r: use an ISO 3166-1 alpha-3 code (DEU), alpha-2 (DE) or an English name (Germany)" % echo(s)
    if hints:
        msg += "; did you mean: " + ", ".join(hints[:5])
    raise CountryError(msg)

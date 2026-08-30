"""
Seed data for the Nigerian Student Diaspora Observatory.

RULE: every row in OBSERVATIONS must trace to a SOURCES entry and a DATASETS
entry with a real, checkable citation. If a number could not be verified from
an authoritative or credibly-cited report, it is NOT included here — it is
listed instead in KNOWN_GAPS at the bottom, so the gap is visible rather than
silently filled.

Sourced during research on 2026-08-24. URLs are the pages the figures were
drawn from at that time; re-verify before using in a submitted report, as
statistics agencies revise published tables.
"""

SOURCES = [
    {
        "short_code": "HESA",
        "name": "Higher Education Statistics Agency",
        "organization_type": "national_statistics_agency",
        "home_country": "United Kingdom",
        "url": "https://www.hesa.ac.uk",
        "reliability_tier": "official_primary",
        "notes": "UK's official statutory body for higher education student data.",
    },
    {
        "short_code": "IIE_OPENDOORS",
        "name": "Institute of International Education — Open Doors Report",
        "organization_type": "ngo_or_press",
        "home_country": "United States",
        "url": "https://opendoorsdata.org",
        "reliability_tier": "official_secondary",
        "notes": "Produced in partnership with the US Department of State; the "
                 "de facto official source for international enrollment in US HE, "
                 "though IIE itself is a non-profit, not a government statistics agency.",
    },
    {
        "short_code": "UNESCO_UIS",
        "name": "UNESCO Institute for Statistics",
        "organization_type": "international_organization",
        "home_country": None,
        "url": "http://uis.unesco.org",
        "reliability_tier": "official_primary",
        "notes": "UN body responsible for global education statistics and outbound "
                 "mobility indicators.",
    },
    {
        "short_code": "WORLDBANK",
        "name": "World Bank — World Development Indicators",
        "organization_type": "international_organization",
        "home_country": None,
        "url": "https://data.worldbank.org",
        "reliability_tier": "official_primary",
        "notes": "Compiles UNESCO UIS data into its own indicator series; treat as "
                 "the same underlying UNESCO source, not an independent count.",
    },
    
{
        "short_code": "DAAD",
        "name": "German Academic Exchange Service (DAAD)",
        "organization_type": "ngo_or_press",
        "home_country": "Germany",
        "url": "https://www.daad.de",
        "reliability_tier": "credible_secondary",
        "notes": "Figures on Nigerian DAAD scholarship recipients drawn from DAAD's 2023 Annual Report, as reported via secondary sources; the primary Annual Report PDF was not directly consulted. Counts only DAAD-funded scholars, not total enrolled Nigerian students in Germany.",
    },
    {
    "short_code": "WENR",
    "name": "World Education News + Reviews (WENR)",
    "organization_type": "ngo_or_press",
    "home_country": "Malaysia",
    "url": "https://wenr.wes.org/2023/01/education-in-malaysia-2",
    "reliability_tier": "credible_secondary",
    "notes": "Nigerian enrollment figures reported in WENR's education-country-profile article on Malaysia, drawing on Malaysian higher-education data. A conflicting press-reported estimate (~13,000/year pre-COVID, ~4,000 in 2022, per a Malaysian government envoy quoted in Nigerian press) exists but was not used as the primary figure, since it is a secondhand spoken estimate rather than a published dataset.",
},
    {
        "short_code": "PRESS_IRCC",
        "name": "News reporting citing Immigration, Refugees and Citizenship Canada",
        "organization_type": "ngo_or_press",
        "home_country": "Canada",
        "url": "https://www.icirnigeria.org/a-look-at-number-of-nigerian-students-studying-abroad/",
        "reliability_tier": "credible_secondary",
        "notes": "Figure is reported via Nigerian press coverage that cites IRCC "
                 "rather than an IRCC table pulled directly. Treat as indicative, "
                 "not authoritative, until confirmed against an IRCC primary release.",
    },
    {
        "short_code": "AGGREGATOR_SCHOOLREG",
        "name": "SchoolRegistry NG (education-sector market blog)",
        "organization_type": "secondary_aggregator",
        "home_country": "Nigeria",
        "url": "https://schoolregistry.ng/education-data/nigerians-studying-abroad",
        "reliability_tier": "unverified",
        "notes": "Not a statistics agency. Figures are rounded estimates with no "
                 "stated methodology. Included only because the app must be able "
                 "to represent low-confidence sources honestly, not hide them.",
    },
]

METRIC_DEFINITIONS = [
    {
        "code": "hesa_enrolled_headcount",
        "name": "HESA enrolled student headcount",
        "description": "Nigerian-domiciled students enrolled at UK higher education "
                        "providers at any point in the academic year, as returned by "
                        "providers to HESA's Student record. Headcount, not FTE.",
        "unit": "count of individuals",
    },
    {
        "code": "sevis_enrolled_headcount",
        "name": "US SEVIS-derived enrolled student count (Open Doors)",
        "description": "Nigerian citizens enrolled at accredited US higher education "
                        "institutions during the academic year, as compiled by IIE from "
                        "institutional survey responses aligned to SEVIS records.",
        "unit": "count of individuals",
    },
    {
        "code": "press_reported_enrollment",
        "name": "Press-reported enrollment figure (unspecified methodology)",
        "description": "A count of students in a given country attributed to a "
                        "government immigration or education agency via secondary "
                        "press reporting. Exact counting methodology (headcount vs "
                        "permit-holders vs new entrants) is not confirmed.",
        "unit": "count of individuals, methodology unconfirmed",
    },
    {
        "code": "unverified_market_estimate",
        "name": "Unverified market-intelligence estimate",
        "description": "A rounded estimate published by an education-sector blog or "
                        "recruitment agency, with no disclosed methodology or primary "
                        "source table. Should never be plotted against an official_primary "
                        "or official_secondary metric without an explicit caveat.",
        "unit": "rounded estimate, methodology undisclosed",
    },
  {
    "code": "unesco_outbound_mobility",
    "name": "UNESCO outbound internationally mobile students",
    "description": "Nigerian nationals enrolled in tertiary education outside Nigeria, as tracked by UNESCO UIS from national reporting systems worldwide. This is a global aggregate, not tied to a single destination country.",
    "unit": "count of individuals",
},
{
    "code": "daad_funded_scholarship_recipients",
    "name": "DAAD-funded scholarship recipients",
    "description": "Nigerian students who received DAAD funding in the given year, as reported in DAAD's Annual Report. This is NOT a total enrolled-student headcount — it counts only scholarship recipients, a subset of all Nigerian students in Germany, and is therefore not directly comparable to HESA or Open Doors enrollment figures.",
    "unit": "count of individuals",
},
{
    "code": "wenr_reported_enrollment",
    "name": "WENR-reported Nigerian enrollment",
    "description": "Nigerian student enrollment in Malaysian higher education institutions, as reported by WENR citing Malaysian education data. Likely represents a total enrollment headcount, but the underlying methodology was not independently verified, so this is kept as a distinct metric rather than merged with HESA/Open Doors enrollment figures.",
    "unit": "count of individuals",
},
]

# Each dataset = one registered release. reference_period stays a string because
# academic years ("2021/22") and calendar years ("2018") are both valid depending
# on the source's own reporting convention -- normalizing them into one type would
# be misleading, not simplifying.
DATASETS = [
    {
    "source": "DAAD", "metric": "daad_funded_scholarship_recipients",
    "title": "DAAD Annual Report — Nigerian scholarship recipients",
    "destination_country": "Germany", "reference_period": "2023",
    "original_url": "https://www.daad.de",
    "limitations": "Counts DAAD-funded scholarship recipients only, not total enrolled Nigerian students in Germany; not comparable to HESA/Open Doors enrollment headcounts. Sourced via secondary reporting of DAAD's 2023 Annual Report, not the primary document itself.",
    "observations": [{"value": 1638}],
},
{
    "source": "WENR", "metric": "wenr_reported_enrollment",
    "title": "WENR Malaysia country profile — Nigerian student enrollment",
    "destination_country": "Malaysia", "reference_period": "2020",
    "original_url": "https://wenr.wes.org/2023/01/education-in-malaysia-2",
    "limitations": "Reported by WENR citing Malaysian higher-education data; underlying primary source and methodology not independently verified. A conflicting press-reported estimate (~13,000/year pre-COVID, ~4,000 in 2022, per a Malaysian government envoy) exists but is not used here, as it is a secondhand spoken figure rather than a published dataset. Peak enrollment was reported at 14,705 in 2016 before declining.",
    "observations": [{"value": 4329}],
},
    {
        "source": "HESA", "metric": "hesa_enrolled_headcount",
        "title": "HESA UK HE student statistics — Nigeria-domiciled students",
        "destination_country": "United Kingdom", "reference_period": "2019/20",
        "original_url": "https://www.icirnigeria.org/a-look-at-number-of-nigerian-students-studying-abroad/",
        "limitations": "See 2018/19 dataset notes.",
        "observations": [{"value": 13020}],
    },
    {
        "source": "HESA", "metric": "hesa_enrolled_headcount",
        "title": "HESA UK HE student statistics — Nigeria-domiciled students",
        "destination_country": "United Kingdom", "reference_period": "2020/21",
        "original_url": "https://www.icirnigeria.org/a-look-at-number-of-nigerian-students-studying-abroad/",
        "limitations": "Academic year affected by pandemic-era travel and visa disruption.",
        "observations": [{"value": 21305}],
    },
    {
        "source": "HESA", "metric": "hesa_enrolled_headcount",
        "title": "HESA UK HE student statistics — Nigeria-domiciled students",
        "destination_country": "United Kingdom", "reference_period": "2021/22",
        "original_url": "https://gslglobal.com/2023/11/17/inbound-insight-nigeria/",
        "limitations": "This is the last year for which a specific aggregate Nigerian "
                        "enrolment figure was found during research. HESA and British "
                        "Council commentary confirm a marked decline occurred in "
                        "2022/23-2023/24 (naira devaluation, dependent-visa policy "
                        "change) but no reconciled headline figure for those years was "
                        "located — do not interpolate or estimate it.",
        "observations": [{"value": 44195}],
    },
    {
        "source": "IIE_OPENDOORS", "metric": "sevis_enrolled_headcount",
        "title": "Open Doors Report — Nigerian students in the United States",
        "destination_country": "United States", "reference_period": "2021/22",
        "original_url": "https://monitor.icef.com/2024/05/data-shows-a-decline-in-nigerian-student-searches-for-study-abroad-uk-may-be-hardest-hit/",
        "limitations": "Derived from institutional survey response rates, not a full census.",
        "observations": [{"value": 14438}],
    },
    {
        "source": "IIE_OPENDOORS", "metric": "sevis_enrolled_headcount",
        "title": "Open Doors Report — Nigerian students in the United States",
        "destination_country": "United States", "reference_period": "2022/23",
        "original_url": "https://monitor.icef.com/2024/05/data-shows-a-decline-in-nigerian-student-searches-for-study-abroad-uk-may-be-hardest-hit/",
        "limitations": "Derived from institutional survey response rates, not a full census.",
        "observations": [{"value": 17640}],
    },
    {
        "source": "IIE_OPENDOORS", "metric": "sevis_enrolled_headcount",
        "title": "Open Doors Report — Nigerian students in the United States",
        "destination_country": "United States", "reference_period": "2023/24",
        "original_url": "https://ng.usembassy.gov/nigeria-ranks-7th-globally-for-international-students-in-the-united-states/",
        "limitations": "Derived from institutional survey response rates, not a full census.",
        "observations": [{"value": 20029}],
    },
    {
        "source": "IIE_OPENDOORS", "metric": "sevis_enrolled_headcount",
        "title": "US institution enrolment figure — Nigerian students",
        "destination_country": "United States", "reference_period": "2024/25",
        "original_url": "https://businessday.ng/news/article/nigerian-students-abroad-surge-98-in-four-years-unesco/",
        "limitations": "Reported as 'nearly 22,000' by press coverage of the "
                        "underlying figure rather than read directly off the primary "
                        "Open Doors release table -- treat the exact integer as "
                        "approximate, not precise.",
        "observations": [{"value": 22000}],
    },
    {
        "source": "PRESS_IRCC", "metric": "press_reported_enrollment",
        "title": "Nigerian students in Canadian universities",
        "destination_country": "Canada", "reference_period": "2021/22",
        "original_url": "https://www.icirnigeria.org/a-look-at-number-of-nigerian-students-studying-abroad/",
        "limitations": "Single data point, no time series located. Counting basis "
                        "(enrolled headcount vs study-permit holders) is not confirmed "
                        "-- do NOT chart directly against HESA/Open Doors figures "
                        "without this caveat visible.",
        "observations": [{"value": 13745}],
    },
    {
        "source": "AGGREGATOR_SCHOOLREG", "metric": "unverified_market_estimate",
        "title": "Estimated Nigerian student population in Malaysia",
        "destination_country": "Malaysia", "reference_period": "~2026 (undated estimate)",
        "original_url": "https://schoolregistry.ng/education-data/nigerians-studying-abroad",
        "limitations": "No disclosed methodology, no primary source table, rounded "
                        "to the nearest 5,000. This is the ONLY category of figure in "
                        "this dataset that should ever be labeled 'unverified' in the UI "
                        "-- it must never be plotted on the same axis as an "
                        "official_primary or official_secondary metric.",
        "observations": [{"value": 10000}],
    },
    {
        "source": "UNESCO_UIS", "metric": "unesco_outbound_mobility",
        "title": "Nigeria total outbound internationally mobile tertiary students",
        "destination_country": "All destinations (global aggregate)", "reference_period": "2018",
        "original_url": "https://trade.gov/country-commercial-guides/nigeria-education-and-training-services-industry-snapshot",
        "limitations": "Global aggregate across all destination countries, cannot be "
                        "broken down by country from this figure alone. World Bank "
                        "republishes the same underlying UNESCO figure.",
        "observations": [{"value": 76338}],
    },
]

# Explicitly documented gaps -- NOT filled with invented numbers.
KNOWN_GAPS = [
    "UK Nigerian enrolment for 2022/23 and 2023/24: qualitative decline is documented "
    "(British Council, HESA commentary) but no reconciled aggregate headline number "
    "was located during research.",
    "Germany: repeatedly cited in secondary sources as a 'rising destination' for "
    "Nigerian students but no verifiable enrolment count was found. Deliberately "
    "excluded rather than estimated.",
    "Field of study / discipline breakdown for Nigerian students specifically: not "
    "located at the country-of-origin level for any destination. HESA publishes "
    "subject-of-study tables but not cross-tabulated by domicile country in the "
    "sources reviewed.",
    "Institution-level breakdown: not available from any source reviewed at this "
    "stage. Requires either a paid dataset or direct HESA/IPEDS microdata access.",
    "Degree-level (undergraduate vs postgraduate) split specifically for Nigerian "
    "students: not located in aggregate form for UK or US in the sources reviewed.",
    "2023 UNESCO 'Nigeria ranks 3rd globally, ~5% of ~7.3 million mobile students' "
    "figure: this is a share of a global total, not a destination-specific headcount, "
    "and is kept separate from the country-level datasets above for that reason.",
]

# External dataset validation — source documentation

## What this is

A **genuinely external, official dataset**, not created, seeded, or modified
for this project, used to test the Phase 3A CSV import pipeline exactly as
an outside user would encounter it.

## Source

- **Publisher:** Department for Education (DfE), UK Government
- **Service:** Explore Education Statistics (part of GOV.UK)
- **Dataset:** "Higher Education Students"
- **Parent publication:** Education and training statistics for the UK,
  Reporting year 2024 (dataset last updated 21 August 2025; the publication
  itself is not the latest release as of access date)
- **Dataset catalogue URL:**
  https://explore-education-statistics.service.gov.uk/data-catalogue/data-set/6c30c91c-e4b5-4598-b048-6b0217055f39
- **License:** Open Government Licence v3.0 (Crown copyright)
- **Accessed:** 2026-08-24, via `web_fetch` of the dataset catalogue page
  (this sandbox's direct CSV/ZIP download endpoints returned bot-detection
  errors; see Limitation below)
- **Official description:** "This file contains information on the number
  of higher education students in the UK, broken down by sex, level of
  education, mode of study, subject group and domicile."
- **Full dataset size:** 4,095 rows, time period 2016/17 to 2022/23,
  geographic level National
- **Filters available in the full dataset:** Domicile, Gender, Level of
  education, Mode of study, Subject group (per the catalogue page)

## What was actually obtained

The dataset catalogue page renders a live preview of the **first 5 rows**
of the underlying data. `source_extract.csv` in this folder is an exact,
unmodified transcription of those 5 rows and their real column headers, as
returned by the official page.

## Limitation — please read before treating this as a full validation

I could not retrieve the complete 4,095-row file. Direct fetches to
`.../data-set/6c30c91c-.../csv` and to the HESA site's own table CSV
exports were blocked by bot-detection in this sandbox
(`CLIENT_ERROR: Site blocked the request`). What follows is therefore a
**real but small** external-data test: 5 genuine official rows, not a
comprehensive stress test of the full file's variation. It's enough to
exercise column mapping, a genuinely new dimension (subject/level of
education), a real normalization gap, and one real duplicate-detection
edge case (all reported below) — but if you want higher-volume validation,
the next step would be for you to download the full ZIP directly (browsers
aren't subject to the same bot-detection) and share it for import.

## Column meanings (from the official page, verbatim field descriptions)

| Column | Description |
|---|---|
| `time_period` | Academic year, concatenated format (e.g. `202223` = 2022/23) |
| `time_identifier` | Period type label ("Academic year") |
| `geographic_level` | Aggregation level ("National") |
| `country_code`, `country_name` | ONS geography code / UK |
| `gender` | Gender |
| `subject` | Subject group |
| `mode_of_study` | Full-time / Part-time |
| `level` | Level of education |
| `domicile` | Student's domicile grouping (`Total` = all domiciles combined in this extract) |
| `t_students` | Number of HE students (an aggregate count, rounded per the dataset's own footnotes) |

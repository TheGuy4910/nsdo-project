# External XLSX dataset validation — source documentation

## What this is

Two **genuinely external, official** DfE datasets — different publication
and different dataset IDs from the one used for Phase 3A's CSV validation
(`Higher Education Students`, dataset `6c30c91c-...`) — combined into one
real multi-sheet `.xlsx` workbook to test workbook/sheet selection.

## Why this file was authored with openpyxl rather than downloaded directly

This sandbox has no way to retrieve raw binary file bytes from the web:
`web_fetch` returns parsed text/markdown content, and outbound network
access from the bash tool is disabled entirely. The official `.xlsx`/ZIP
download endpoints for these datasets also returned bot-detection errors
when their catalogue pages were fetched directly.

What I *could* retrieve, for both datasets, is the exact 5-row preview
table the official DfE catalogue page itself renders (server-rendered
HTML, not client-side JS). `workbook_source.xlsx` in this folder is that
real, cited data, transcribed exactly and written into a genuine `.xlsx`
container using openpyxl so the import pipeline has an authentic workbook
to parse. **The container was built by this code; the values inside it
were not.** No student count, percentage, or category label in this file
was invented -- every one was copied character-for-character from the
official page.

## Sheet 1: `FSM_Sex_Ethnicity`

- **Dataset:** "Free School Meals, Sex and Ethnic Group"
- **Publication:** Widening participation in higher education, Academic
  year 2024/25 release
- **Publisher:** Department for Education (DfE), UK Government
- **Catalogue URL:**
  https://explore-education-statistics.service.gov.uk/data-catalogue/data-set/25bdb203-59b9-4829-90f7-715da67157e3
- **License:** Open Government Licence v3.0
- **Published:** 9 July 2026 · **Accessed:** 2026-08-24
- **Full dataset size:** 13,626 rows, time period 2005/06-2021/22
- A title row ("Free School Meals, Sex and Ethnic Group -- DfE Widening
  participation in higher education, extracted 2026-08-24") was added
  above the real header row to test header-row detection against a sheet
  that doesn't start with data on row 1. That title text is an accurate
  label of this sheet's real content, not a data value.

## Sheet 2: `All_Characteristics`

- **Dataset:** "All Characteristics"
- **Publication:** Widening participation in higher education, Academic
  year 2023/24 release
- **Publisher:** Department for Education (DfE), UK Government
- **Catalogue URL:**
  https://explore-education-statistics.service.gov.uk/data-catalogue/data-set/168795a4-26a0-4b29-8b9e-442b5e5f9fcf
- **License:** Open Government Licence v3.0
- **Published:** 31 July 2025 · **Accessed:** 2026-08-24
- **Full dataset size:** 745 rows, time period 2009/10-2023/24
- Header row starts on row 1 (no title row) -- deliberately different from
  Sheet 1, to test that header detection doesn't assume a fixed row number.

## Limitation

Same as the CSV validation: these are 5-row official previews, not the
complete underlying files (13,626 and 745 rows respectively). Real,
unmodified, and sufficient to exercise the importer's mechanics, but not a
high-volume stress test. The full files would need to be downloaded
directly (outside this sandbox's network restrictions) for that.

## Column meanings

| Column | Sheet(s) | Description (from the official page) |
|---|---|---|
| `time_period` | both | Academic year, concatenated YYYYYY form |
| `country_name` | both | Geography name ("England") |
| `sex` | 1 only | Sex |
| `entry_age`, `fsm_status`, `ethnicity_major`, `ethnicity_minor` | 1 only | Characteristics this project doesn't model |
| `breakdown_topic`, `breakdown` | 2 only | Generic characteristic-grouping columns this project doesn't model |
| `number_of_he_students` | both | The actual HE student count -- mapped to `student_count` |
| `number_of_high_tariff_he_students`, `number_of_students`, `participation_rate`, `high_tariff_participation_rate`, `progression_rate`, `high_tariff_progression_rate` | both | Related indicators, not the primary count, left unmapped |

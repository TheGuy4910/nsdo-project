# Test fixtures — provenance

## hesa_uk_real_figures.csv

**Real data.** These are the exact same four HESA UK Nigerian-student
headcounts already verified and cited in `backend/seed/seed_data.py`
(source: Higher Education Statistics Agency, via the URLs already recorded
in that file). They are reformatted here as a raw CSV purely so the
importer has something real to parse -- no new numbers, no new claims about
reality are introduced by this file. Used in
`test_csv_import.py::TestRealFixtureEndToEnd`.

## SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv

**Fabricated, for mechanics testing only.** Every value in this file is
made up and does not describe any real students, institution, or country
statistic. It exists solely to exercise validation logic that the real
fixture above doesn't happen to trigger:

- row 2: `UK` vs row 1's `United Kingdom` -- tests country normalization
- row 2 is also a duplicate of row 1 in every other mapped dimension --
  tests duplicate detection
- row 3: negative student_count -- tests the negative-value rule
- row 4: `not-a-year` -- tests the invalid-year-format rule
- row 5: `Narnia` (unrecognized country) and `not-a-number` (invalid count)
  -- tests malformed-record handling

**This file must never be imported as if it were real data**, and no
dataset created from it should ever be marked `verified`. It is referenced
only from `test_csv_import.py`, never from any seed or demo data path.

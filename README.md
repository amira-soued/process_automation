# process_automation

## Run locally

Run these commands from the repository root on macOS or Linux using Python
3.9 or later.

### Install dependencies

Create and activate a virtual environment, then install HTTPX.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install httpx
```

### Run the application

Fetch the raw records from the mocked HTTP source and print them as JSON.

```sh
python fetch_meter_exchanges.py
```

Fetch the records, validate them, and save the report.

```sh
python fetch_meter_exchanges.py --validate > validation-report.json
```

Both commands use `data/meter_exchange_data.csv` by default. Pass a CSV path
as an argument to use a different file.

A source error prints a message to standard error and exits with a nonzero
status. Row-level validation errors are recorded in the report, and processing
continues with the remaining rows.

### Run the tests

```sh
python -m unittest -v test_validation
```

The tests cover cleaning, validation rules, the supplied CSV, and a mocked
HTTP 503 from the source API.

### Find the generated report

The validation command saves `validation-report.json` in the repository root.
The report contains counts, cleaned eligible records, exceptions, and warnings.
Row numbers count CSV records with the header as row 1. Each issue identifies
the field, category, and reason. Warning counts include warnings on blocked rows.

## Validation decisions

- **Structure and order numbers.** The source needs the 14 named columns and
  unambiguous headers. Trim surrounding whitespace. Keep order numbers as
  five-digit strings, including leading zeros. Hold every occurrence of a
  repeated order number until the intended exchange is confirmed.
- **Meters and placement.** Remove hyphens from old and new meter identifiers,
  preserving letters, case, and leading zeros. Accept alphanumeric IDs of
  different lengths. Hold blank, all-zero, or identical old and new IDs. A
  missing old ID on a PV job may indicate a first installation. Verify the
  job type before treating it as an exchange. Require a placement and preserve
  its wording and punctuation.
- **Readings.** Require all four nonnegative register readings and preserve
  measured zeros. Parse ungrouped numbers exactly, using a comma as the German
  decimal separator. Accept unambiguous decimal points. Hold forms such as
  `1.234` that could mean 1234 or a fractional value. Emit decimal strings
  without rounding. Flag a positive installation reading on either register
  for verification. A reused meter can carry a prior total, so this is a
  warning. The destination's handling of fractional readings with
  the template's fixed `fractionalPart: 0` needs confirmation at the mapping stage.
- **Time.** Interpret the specified day-month-year and hour-minute format in
  Europe/Berlin and emit UTC. Hold impossible dates and times in the missing
  or repeated hour at a daylight-saving transition.
- **Gateway.** Require a nonempty identifier and hold an all-zero placeholder.
  An identifier outside the observed ETHE-plus-ten-digits pattern gets a
  warning. The brief gives no exclusive gateway format. A gateway can serve
  several meters.
- **Address.** Expand street abbreviations such as `Rappenauer Str.` and
  preserve house numbers and city names as text. Warn about missing address
  fields or a postal code other than five digits. The address is absent from
  the finish-order mapping, so these warnings allow the exchange to proceed.
  Preserve a short postal code for review rather than supplying a digit.

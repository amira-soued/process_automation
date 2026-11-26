# process_automation

## Fetch and validate meter exchanges

From the repository root, install HTTPX in your Python environment with
`python3 -m pip install httpx`. Run the validation and its tests with:

```sh
python3 fetch_meter_exchanges.py --validate > validation-report.json
python3 -m unittest -v test_validation
```

The command fetches the original strings through the mocked HTTP source.
Without `--validate` it prints those raw records. Both modes accept an optional
CSV path. A source error exits with a nonzero status. A completed validation
run reports row exceptions in JSON so one incomplete exchange can be skipped.

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

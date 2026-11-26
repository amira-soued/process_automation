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

Run the full pipeline and configure the mock destination to return HTTP 422
for order `24592`.

```sh
python fetch_meter_exchanges.py --submit --fail-order 24592
```

In submission mode, the application fills the placeholders in
`data/meter_exchange_payload.json` with cleaned values from each eligible row.
It preserves fixed template fields and sends each payload as a separate HTTPX
`POST` to an in-memory mock. A row with blocking validation issues is skipped.
The `--fail-order` option selects which eligible order the mock rejects.

All modes use `data/meter_exchange_data.csv` by default. Pass a CSV path as an
argument to use a different file.

The source `GET` waits 250 ms and retries once if the connection fails to open
or times out while opening (`ConnectError` or `ConnectTimeout`). Repeating this
read can recover from a temporary connection problem. The run stops with a
clear error and a nonzero exit status if both attempts fail. HTTP status errors
and timeouts while reading the response are reported immediately.

Validation errors and destination failures are recorded by row, and processing
continues with the remaining orders. Each submission gets one attempt. A timeout
waiting for the reply can leave the order's status unknown, so the report asks
for verification before resubmitting.

### Run the tests

```sh
python -m unittest -v test_validation
```

The suite covers cleaning, validation, and the supplied CSV. Source tests check
recovery on the second `GET` after a connection error or connection timeout,
failure after two attempts, and a single attempt for HTTP 503.
The payload test checks the meter IDs, register
readings, UTC timestamp, repeated gateway and placement values, and fixed
template fields. The destination tests simulate HTTP 422, a read timeout,
and a connection failure. They check that the affected order is reported
once, blocked validation rows are skipped, and later eligible rows still
reach the destination.

### Find the generated outputs

The validation command above saves `validation-report.json` with cleaned
eligible records, exceptions, warnings, and counts.

The submission command prints summary counts and writes two files in the
repository root. Use `--output-dir` to choose another folder.

- **`run-report.json`** contains batch counts, all validation and submission
  exceptions, and warnings. Each exception includes the CSV row number, order
  number when available, stage, and an issue list with categories and readable
  reasons. HTTP status errors also include the numeric status.
- **`example-payload.json`** contains the JSON body from the first accepted
  submission. It contains JSON `null` if the destination accepts no orders.

Row numbers count CSV records with the header as row 1. Warning counts
include warnings on blocked rows. With the supplied CSV and
`--fail-order 24592`, the run creates 58 payloads. The mock accepts 57 and
rejects one. Four other rows are blocked by validation.

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
  warning. The mock accepts normalized decimal strings with the template's
  fixed `fractionalPart: 0`. Confirm that representation with the destination
  contract before integrating with a real service.
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

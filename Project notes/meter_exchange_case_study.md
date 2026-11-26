# Take-home assignment: Automating meter-exchange payloads

**Role:** Process Automation Engineer Intern <br>
**Estimated time:** 3–4 hours <br>
**Language:** Python <br>

## 1. Introduction

Our electricians replace old electricity meters with new ones in multi-family homes. After completing a job, the electrician submits the results (meter numbers, readings, placement) in a field-service app. The app sends the data to our backend, which stores it as one record per meter exchange. In production, you would fetch these records through an API that the backend exposes. For this assignment, the records are provided as a CSV file.

Each CSV row is one meter exchange: the address, the removed meter, the newly installed meter, the readings, where the new meter was placed, and the smart meter gateway (SMGW) it is connected to.

Now we need to implement each meter exchange in our ERP system, which then reports it to the energy market. We call this "finishing" the order. A downstream interface handles this. It accepts a JSON `finish-order` payload, and `meter_exchange_payload.json` is an example of that payload.

**Your job is to build the automation:** fetch the electrician data, clean and validate it, turn each valid record into a `finish-order` payload, and submit it to the interface.

## 2. Provided files

Both files are in the `data/` folder.

| File | Purpose |
|---|---|
| `data/meter_exchange_data.csv` | Raw records from the electricians (semicolon-separated, encoding `utf-8`). Stands in for the response of our system's API. |
| `data/meter_exchange_payload.json` | Example of the target `finish-order` payload. |

The CSV is **deliberately imperfect**: it was typed by humans on a construction site. Addresses and meter numbers are fictional.

Columns:

| Column | Meaning |
|---|---|
| `order_no` | Order number of this meter exchange (5 digits). Use it as `orderNo` in the payload. |
| `exchange_date` | Date and time at which the electrician performed the exchange (`DD.MM.YYYY HH:MM`, German local time). Use it for `executionDate` in the payload. |
| `street`, `number`, `postal_code`, `city` | Address of the building. |
| `meter_number_old` | Number of the removed meter. |
| `meter_reading_demount_1.8.0` | Final reading of the old meter, consumption register (1.8.0). |
| `meter_reading_demount_2.8.0` | Final reading of the old meter, feed-in register (2.8.0). |
| `meter_number_new` | Number of the newly installed meter. |
| `meter_placement` | Free-text label for where the new meter was installed (e.g. "1 OG. Links"). |
| `meter_reading_mount_1.8.0` | Reading of the new meter after installation, consumption register (1.8.0). |
| `meter_reading_mount_2.8.0` | Reading of the new meter after installation, feed-in register (2.8.0). |
| `smgw_number` | Number of the smart meter gateway the meter is connected to. |

`data/meter_exchange_payload.json` is the example payload. <br>
Position 1 is the meter exchange (mounting and demounting device with their counting devices). Positions 2 and 3 relate to the gateway, and the gateway is always part of the payload. Every `{{PLACEHOLDER}}` in the example must be filled from the CSV (see the table in 3.1). All other values in the example, such as `gateway_model_1` as the gateway `deviceModel`, are fixed.

## 3. Your task

```text
fetch records (mock API)  ->  clean & validate  ->  build finish-order payload  ->  POST (mock API)  ->  summary + exception report
```

Create **one `finish-order` payload per eligible CSV row**. A bad row must not stop the batch: skip it and list it in a machine-readable exception report (e.g. `run-report.json`) with the row number, an error category, and a human-readable reason.

### 3.1 Mapping

| Placeholder in example payload | CSV column | Notes |
|---|---|---|
| `{{ORDER_NO}}` | `order_no` | |
| `{{EXECUTION_DATE_UTC}}` | `exchange_date` | `executionDate` in the payload is UTC. |
| `{{NEW_METER_NUMBER}}` | `meter_number_new` | |
| `{{NEW_READING_180}}` | `meter_reading_mount_1.8.0` | |
| `{{NEW_READING_280}}` | `meter_reading_mount_2.8.0` | |
| `{{OLD_METER_NUMBER}}` | `meter_number_old` | Refer to 3.2. |
| `{{OLD_READING_180}}` | `meter_reading_demount_1.8.0` | |
| `{{OLD_READING_280}}` | `meter_reading_demount_2.8.0` | |
| `{{GATEWAY_NUMBER}}` | `smgw_number` | |
| `{{DEVICE_LOCATION}}` | `meter_placement` | |


### 3.2 Data validation and normalization

Based on the minimal information above, define your **data validation and normalization** rules (sanitization, standardization, format enforcement) to ensure data quality. For each field, decide:

- where you enforce a specific format, and why;
- what you reject and how you report it.

Two examples of rules we apply:

- Meter numbers must not contain any hyphens. `SLE00501-17-10056` must be parsed to `SLE005011710056`.
- German street names are always fully written out. An abbreviation like `Str.` must become `Straße`.

**These are only examples. Look at the data and find potential issues. We expect a reasoned decision: what might an incomplete or faulty row represent in reality, what does the downstream system need, and what does a wrong guess cost?**

Never silently replace ambiguous or invalid values with plausible-looking ones.

## 4. Mock APIs

The data source and the destination are APIs, and both are to be mocked. Your code must call them through an HTTP client library (for example `requests` or `httpx`). Use whatever mocking approach you prefer: `responses`, `requests-mock`, `respx`, or a small local server. The source mock returns the CSV rows as a JSON list of objects, using the CSV column names as keys and the values exactly as they are in the CSV. Cleaning is done by your application. The destination mock accepts a `POST` with a JSON body and can fail for at least one case (for example one configured `order_no`). Do not call any real company or third-party service.

Your pipeline must handle API errors (non-2xx, timeout, connection failure) sensibly: fail clearly if the source cannot be fetched, and tie destination failures to the affected record without stopping the others. Retries are optional. If you add them, keep them bounded; if you don't, tell us why.

## 5. Deliverables

- Your source code.
- A few automated tests, focused on the data handling, e.g. a valid record, a missing required field, a missing gateway number, a malformed number, your cleaning rules, a source API error, and a destination API error.
- Short instructions on how to run the application locally.
- One generated example payload and one generated exception report.
- A short note covering:
  - what you focused on;
  - your data cleaning and validation rules and your assumptions;
  - what you intentionally simplified or left out;
  - what you would improve next with more time.

## 6. Presentation

You will present your solution in person and walk us through:

- your implementation;
- your decisions;
- your next steps if you had more time.

The presentation should be explainable in roughly **15–20 minutes**.

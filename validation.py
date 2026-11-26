"""Clean and validate meter exchanges before building finish-order payloads."""

import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo


ADDRESS_FIELDS = ("street", "number", "postal_code", "city")
METER_FIELDS = ("meter_number_old", "meter_number_new")
INSTALLATION_READING_FIELDS = ("meter_reading_mount_1.8.0", "meter_reading_mount_2.8.0")
READING_FIELDS = (
    "meter_reading_demount_1.8.0", "meter_reading_demount_2.8.0",
    *INSTALLATION_READING_FIELDS,
)
REQUIRED_FIELDS = ("order_no", "exchange_date", *METER_FIELDS, *READING_FIELDS,
                   "meter_placement", "smgw_number")
SOURCE_FIELDS = (*REQUIRED_FIELDS, *ADDRESS_FIELDS)
BERLIN = ZoneInfo("Europe/Berlin")


def check_columns(columns: list[str]) -> None:
    """Missing or repeated headers make the source layout unreliable."""
    missing = sorted(set(SOURCE_FIELDS) - set(columns))
    repeated = sorted(name for name, count in Counter(columns).items() if count > 1)
    if missing or repeated:
        raise ValueError(f"Invalid CSV header. Missing columns: {missing}. "
                         f"Repeated columns: {repeated}.")


def utc_timestamp(value: str) -> str:
    # The source uses German local time. The payload needs an unambiguous UTC time.
    date_format = "%d.%m.%Y %H:%M"
    try:
        local = datetime.strptime(value, date_format)
    except ValueError:
        raise ValueError("Expected a real date and time in DD.MM.YYYY HH:MM format.") from None
    if local.strftime(date_format) != value:
        raise ValueError("Expected a date and time in DD.MM.YYYY HH:MM format.")

    # Round-trip both interpretations of a local clock time at a DST transition.
    candidates = set()
    for fold in (0, 1):
        utc = local.replace(tzinfo=BERLIN, fold=fold).astimezone(timezone.utc)
        if utc.astimezone(BERLIN).replace(tzinfo=None) == local:
            candidates.add(utc)
    if len(candidates) != 1:
        raise ValueError("Local time is ambiguous or nonexistent in Europe/Berlin.")
    return candidates.pop().isoformat(timespec="seconds").replace("+00:00", "Z")


def decimal_reading(value: str) -> str:
    # Zero is a valid reading. Accept decimal commas and preserve the recorded precision.
    if not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", value):
        raise ValueError("Expected a nonnegative, ungrouped meter reading.")
    if re.fullmatch(r"[1-9][0-9]{0,2}\.[0-9]{3}", value):
        raise ValueError("The dot could be a thousands separator. Confirm the reading.")
    return format(Decimal(value.replace(",", ".")), "f")


def issue(field: str, category: str, reason: str) -> dict:
    return {"field": field, "category": category, "reason": reason}


def validate_record(raw: dict, duplicate_orders: set[str]) -> tuple[dict, list, list]:
    """Build a separate cleaned record and collect every issue for this exchange."""
    cleaned = {}
    errors = []
    warnings = []
    if any(isinstance(value, list) for value in raw.values()):
        errors.append(issue("row", "invalid_structure", "Row contains extra CSV cells."))
    # Trim outer whitespace while preserving free-text labels such as "Aufzug".
    # Missing payload fields block the order. Missing address fields trigger a warning.
    for field in SOURCE_FIELDS:
        value = raw.get(field)
        cleaned[field] = value.strip() if isinstance(value, str) else ""
        if not cleaned[field]:
            reason = "A value is required to finish this order."
            if field == "meter_number_old":
                reason = "Old meter ID is missing. Confirm removal or a possible first installation."
            if field in REQUIRED_FIELDS:
                errors.append(issue(field, "missing_required_field", reason))
            else:
                warnings.append(issue(field, "incomplete_address", "Address field is missing."))

    # Order numbers are exactly five digits. Keep them as text to preserve leading zeros.
    order = cleaned["order_no"]
    if order and not re.fullmatch(r"[0-9]{5}", order):
        errors.append(issue("order_no", "invalid_order", "Expected exactly five digits."))
    if order in duplicate_orders:
        errors.append(issue("order_no", "duplicate_order", "Multiple records have this order number."))

    if cleaned["exchange_date"]:
        try:
            cleaned["exchange_date"] = utc_timestamp(cleaned["exchange_date"])
        except ValueError as exc:
            errors.append(issue("exchange_date", "invalid_date", str(exc)))

    # Remove hyphens from both meter IDs. Keep letters and leading zeros intact.
    for field in METER_FIELDS:
        if cleaned[field]:
            identifier = cleaned[field].replace("-", "")
            cleaned[field] = identifier
            if not re.fullmatch(r"[A-Za-z0-9]+", identifier) or not identifier.strip("0"):
                errors.append(issue(field, "invalid_meter_id",
                                    "Expected an identifiable meter. Confirm the device number."))
    # An exchange needs two distinct devices. Compare IDs after removing hyphens.
    if cleaned["meter_number_old"] and cleaned["meter_number_old"] == cleaned["meter_number_new"]:
        errors.append(issue("meter_number_old", "same_meter",
                            "Old and new meter IDs match after normalization. Confirm replacement."))

    for field in READING_FIELDS:
        if not cleaned[field]:
            continue
        try:
            reading = decimal_reading(cleaned[field])
        except ValueError as exc:
            errors.append(issue(field, "invalid_reading", str(exc)))
            continue
        cleaned[field] = reading

        # A reused meter can carry a prior total. The CSV gives the reading after
        # installation, so flag positive values for verification against a known baseline.
        if field in INSTALLATION_READING_FIELDS and Decimal(reading) > 0:
            register = field.removeprefix("meter_reading_mount_")
            meter_id = cleaned["meter_number_new"] or "(ID missing)"
            warnings.append(issue(
                field, "nonzero_installation_reading",
                f"Verify that {reading} was read from register {register} "
                f"on installed meter {meter_id}.",
            ))

    # Hold all-zero gateway IDs as suspected placeholders. ETHE is an observed pattern,
    # so a different prefix triggers a warning until the gateway can be verified.
    gateway = cleaned["smgw_number"]
    if gateway and not gateway.strip("0"):
        errors.append(issue("smgw_number", "invalid_gateway", "All-zero gateway ID needs confirmation."))
    elif gateway and not re.fullmatch(r"ETHE[0-9]{10}", gateway):
        warnings.append(issue("smgw_number", "unusual_gateway",
                              "Gateway differs from the usual ETHE format. Verify against inventory."))

    # Expand "Str." to "Straße" 
    cleaned["street"] = re.sub(r"(?i)str\.(?=\s|$)",
                               lambda m: "straße" if m.group()[0].islower() else "Straße",
                               cleaned["street"])
    # Flag postal codes outside the five-digit format. Guessing a missing digit could change the address.
    postal_code = cleaned["postal_code"]
    if postal_code and not re.fullmatch(r"[0-9]{5}", postal_code):
        warnings.append(issue("postal_code", "invalid_postal_code",
                              "Expected five digits. Verify the address before correcting it."))
    return cleaned, errors, warnings


def validate_batch(records: list[dict]) -> dict:
    """Check duplicates before allowing any occurrence of an order through."""
    order_counts = Counter(row["order_no"].strip() for row in records
                           if isinstance(row.get("order_no"), str) and row["order_no"].strip())
    duplicate_orders = {order for order, count in order_counts.items() if count > 1}
    eligible = []
    exceptions = []
    warnings = []
    for row_number, raw in enumerate(records, start=2):
        cleaned, errors, row_warnings = validate_record(raw, duplicate_orders)
        where = {"row_number": row_number, "order_no": cleaned["order_no"]}
        if errors:
            exceptions.append({**where, "issues": errors})
        else:
            eligible.append({"row_number": row_number, "record": cleaned})
        if row_warnings:
            warnings.append({**where, "issues": row_warnings})
    return {
        "summary": {"fetched": len(records), "eligible": len(eligible),
                    "blocked": len(exceptions), "rows_with_warnings": len(warnings)},
        "eligible_records": eligible,
        "exceptions": exceptions,
        "warnings": warnings,
    }

# Implementation reasoning

## Goal

PulseDesk is designed for a small clinic front desk where the highest-risk operation is booking two patients into overlapping time for one doctor. Billing and medicine dispensing are secondary workflows, but they need durable records because refunds, fees, stock, and prescription checks should be auditable.

## Main decisions

### SQLite as the first persistence layer

SQLite keeps local setup simple and is sufficient for a small clinic deployment. The schema uses foreign keys, indexes for doctor/time and patient lookup, and additive startup migrations so an earlier appointment database can gain the new billing fields without losing existing records.

### Transactional booking

Booking begins an `IMMEDIATE` transaction before checking the doctor schedule. The overlap predicate is:

`existing.start_at < requested_end AND existing.end_at > requested_start`

This permits back-to-back visits while rejecting partial and full overlaps. The check and insert happen in the same transaction to reduce race conditions between two front-desk users.

### Fee model

Each doctor owns a consultation fee. Each appointment receives a fixed ₹50 booking fee, and `total_amount` stores the sum at booking time. Storing the values on the appointment prevents later doctor-price changes from changing historical invoices.

### Cancellation and refunds

Cancellation records the actor instead of deleting the appointment:

- `doctor`: refund the full appointment total.
- `patient`: retain 15% of the total and record the ₹25 late fee when cancellation is inside 24 hours.
- `desk`: supported for operational corrections and currently follows the no-late-fee refund calculation.

The original appointment remains available for audit history, while active schedule queries filter it out.

### Rescheduling

A patient can change an active appointment twice. Rescheduling updates the existing row and increments `reschedule_count`, while using the same doctor overlap check inside a transaction. A conflict or a third attempt returns `409`.

### Prescription-gated medicine counter

The medicine counter cannot create an order from an appointment alone. The desk must first create a prescription verification record containing a file name and a note that says the prescription is signed or stamped. Medicine inventory is then decremented transactionally when an order is recorded.

## Tradeoffs and known limits

- The current prescription flow stores file metadata and the desk's verification note; it does not yet upload or cryptographically verify a document.
- The current API uses a session cookie and does not yet have staff roles, so the caller supplies whether a cancellation was from the patient or doctor side. Production use should enforce that distinction with authenticated roles or a doctor action flow.
- SQLite is appropriate for a small deployment. A larger clinic network would likely move to PostgreSQL and use a database-level exclusion constraint for time ranges.
- Money is represented as SQLite `REAL` values for this prototype. A production billing system should use integer paise or a decimal database type.

## Validation approach

The focused smoke scenario verifies page rendering, registration, doctor fees, appointment total calculation, overlap rejection, one reschedule, prescription verification, medicine ordering, and a full doctor-side refund. Python bytecode compilation and frontend JavaScript syntax checks are also run before completion.

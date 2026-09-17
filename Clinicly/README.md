# PulseDesk

PulseDesk is an India-ready clinic front-desk scheduler for small practices. It protects doctors from overlapping appointments, calculates consultation and booking charges in INR, handles refunds and patient rescheduling, and gates medicine dispensing behind prescription verification.

## Run locally

```bash
cd "Pulse Desk"
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. SQLite is created automatically at `pulsedesk.db`. Set `PULSEDESK_DATABASE` and `PULSEDESK_SECRET_KEY` in production. The server applies additive migrations when opening an older database.

## Product rules

- Each doctor has a consultation fee. Every booking adds a ₹50 booking fee.
- Overlapping appointments for the same doctor return `409 Conflict`; adjacent slots are allowed.
- Doctor-side cancellation refunds 100% of the appointment total.
- Patient-side cancellation retains 15% of the total and records a ₹25 late fee inside the 24-hour notice window.
- An active appointment can be moved twice, subject to the doctor's availability.
- The medicine counter requires a prescription record whose verification note contains `signed` or `stamped` before stock can be dispensed.

## API

Authentication uses the Flask session cookie created by registration or login. Appointment listing supports `page`, `per_page`, `search`, `date`, `sort` (`start_at`, `patient_name`, or `doctor`), and `order` (`asc` or `desc`).

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/register` | Create an account and sign in |
| `POST` | `/api/auth/login` | Sign in |
| `POST` | `/api/auth/logout` | End the session |
| `GET` | `/api/auth/me` | Get the current user |
| `GET` | `/api/doctors` | List doctors and consultation fees; optional `search` |
| `GET` | `/api/appointments` | Search, sort, filter, and paginate active appointments |
| `POST` | `/api/appointments` | Book and price an appointment |
| `POST` | `/api/appointments/<id>/cancel` | Cancel as `patient`, `doctor`, or `desk`; calculate fee/refund |
| `POST` | `/api/appointments/<id>/reschedule` | Move an appointment, maximum twice |
| `GET` | `/api/medicines` | List in-stock medicines and INR prices |
| `POST` | `/api/prescriptions` | Verify a signed/stamped prescription record |
| `POST` | `/api/medicine-counter` | Dispense medicine after prescription verification |

### Booking payload

```json
{
  "doctor_id": 1,
  "patient_name": "Asha Rao",
  "patient_email": "asha@example.in",
  "start_at": "2026-09-18T09:00:00+00:00",
  "end_at": "2026-09-18T09:30:00+00:00"
}
```

### Cancellation payload

```json
{
  "cancelled_by": "doctor",
  "reason": "Doctor unavailable"
}
```

### Prescription and medicine payloads

The prescription endpoint stores a file name and verification note. The note must explicitly say `signed` or `stamped`.

```json
{
  "appointment_id": 12,
  "doctor_id": 5,
  "file_name": "asha-prescription.pdf",
  "verification_note": "Signed by Dr. Mehta"
}
```

Then use the returned `prescription_id` with `/api/medicine-counter` and a `medicine_id` from `/api/medicines`.

## Persistence schema

SQLite stores `users`, `doctors`, `appointments`, `prescriptions`, `medicines`, and `medicine_orders`. Passwords are stored as hashes. Appointment rows retain consultation fee, booking fee, total, refund, cancellation actor, cancellation reason, and reschedule count. Doctor/time, patient, and medicine stock queries are indexed or constrained by foreign keys.

## UI status

The public page and authenticated front-desk UI cover registration, login, booking, search, sorting, pagination, doctor-specific visual themes, and appointment cancellation. The billing and medicine flows are fully available through the documented REST APIs; the next UI slice should expose the prescription upload/verification and medicine-counter forms directly in the workspace.

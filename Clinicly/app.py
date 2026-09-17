"""Clinicly: a persistent clinic scheduling application."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("PULSEDESK_DATABASE", BASE_DIR / "pulsedesk.db"))
LATE_CANCELLATION_FEE = 25.0
CANCELLATION_NOTICE = timedelta(hours=24)
BOOKING_FEE = 50.0

app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("PULSEDESK_SECRET_KEY", "dev-only-change-me"), DATABASE=DATABASE)


def get_db() -> sqlite3.Connection:
	if "db" not in g:
		g.db = sqlite3.connect(app.config["DATABASE"])
		g.db.row_factory = sqlite3.Row
		g.db.execute("PRAGMA foreign_keys = ON")
	return g.db


@app.teardown_appcontext
def close_db(_: BaseException | None) -> None:
	db = g.pop("db", None)
	if db is not None:
		db.close()


def init_db() -> None:
	db = get_db()
	db.executescript("""
	CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
	CREATE TABLE IF NOT EXISTS doctors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE, specialty TEXT NOT NULL, consultation_fee REAL NOT NULL DEFAULT 500);
	CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, doctor_id INTEGER NOT NULL REFERENCES doctors(id), patient_name TEXT NOT NULL, patient_email TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'booked' CHECK(status IN ('booked', 'cancelled')), cancellation_fee REAL NOT NULL DEFAULT 0, consultation_fee REAL NOT NULL DEFAULT 0, booking_fee REAL NOT NULL DEFAULT 50, total_amount REAL NOT NULL DEFAULT 0, refund_amount REAL NOT NULL DEFAULT 0, cancelled_by TEXT, cancellation_reason TEXT, reschedule_count INTEGER NOT NULL DEFAULT 0, rescheduled_from INTEGER REFERENCES appointments(id), created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
	CREATE TABLE IF NOT EXISTS prescriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, appointment_id INTEGER NOT NULL REFERENCES appointments(id), doctor_id INTEGER NOT NULL REFERENCES doctors(id), patient_name TEXT NOT NULL, file_name TEXT NOT NULL, verification_note TEXT NOT NULL, verified_at TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id));
	CREATE TABLE IF NOT EXISTS medicines (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, strength TEXT NOT NULL, price REAL NOT NULL, stock INTEGER NOT NULL DEFAULT 0);
	CREATE TABLE IF NOT EXISTS medicine_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, appointment_id INTEGER NOT NULL REFERENCES appointments(id), prescription_id INTEGER NOT NULL REFERENCES prescriptions(id), medicine_id INTEGER NOT NULL REFERENCES medicines(id), quantity INTEGER NOT NULL, amount REAL NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
	CREATE INDEX IF NOT EXISTS appointments_doctor_time ON appointments(doctor_id, start_at, end_at);
	CREATE INDEX IF NOT EXISTS appointments_patient ON appointments(patient_name COLLATE NOCASE);
	""")
	seed_doctors = [("Dr. Maya Chen", "Family medicine", 600), ("Dr. Elias Morgan", "Pediatrics", 700), ("Dr. Priya Shah", "Internal medicine", 800), ("Dr. Ananya Iyer", "Dentistry", 900), ("Dr. Rohan Mehta", "General medicine", 500)]
	db.executemany("INSERT OR IGNORE INTO doctors(name, specialty, consultation_fee) VALUES (?, ?, ?)", seed_doctors)
	for statement in ("ALTER TABLE doctors ADD COLUMN consultation_fee REAL NOT NULL DEFAULT 500", "ALTER TABLE appointments ADD COLUMN consultation_fee REAL NOT NULL DEFAULT 0", "ALTER TABLE appointments ADD COLUMN booking_fee REAL NOT NULL DEFAULT 50", "ALTER TABLE appointments ADD COLUMN total_amount REAL NOT NULL DEFAULT 0", "ALTER TABLE appointments ADD COLUMN refund_amount REAL NOT NULL DEFAULT 0", "ALTER TABLE appointments ADD COLUMN cancelled_by TEXT", "ALTER TABLE appointments ADD COLUMN cancellation_reason TEXT", "ALTER TABLE appointments ADD COLUMN reschedule_count INTEGER NOT NULL DEFAULT 0", "ALTER TABLE appointments ADD COLUMN rescheduled_from INTEGER"):
		try:
			db.execute(statement)
		except sqlite3.OperationalError:
			pass
	db.executemany("INSERT OR IGNORE INTO medicines(name, strength, price, stock) VALUES (?, ?, ?, ?)", [("Paracetamol", "500 mg", 35, 120), ("Cetirizine", "10 mg", 60, 80), ("Amoxicillin", "500 mg", 140, 40), ("ORS Sachets", "21 g", 25, 100)])
	db.execute("UPDATE appointments SET total_amount = consultation_fee + booking_fee WHERE total_amount = 0")
	db.commit()


def now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def parse_datetime(value: str) -> datetime:
	try:
		parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
	except (AttributeError, ValueError) as error:
		raise ValueError("Use an ISO date and time") from error
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=timezone.utc)
	return parsed.astimezone(timezone.utc)


def appointment_json(row: sqlite3.Row) -> dict:
	return {key: row[key] for key in ("id", "doctor_id", "patient_name", "patient_email", "start_at", "end_at", "status", "cancellation_fee", "consultation_fee", "booking_fee", "total_amount", "refund_amount", "cancelled_by", "reschedule_count")} | {"doctor": row["doctor_name"], "specialty": row["specialty"]}


def require_login(function):
	@wraps(function)
	def wrapped(*args, **kwargs):
		if "user_id" not in session:
			return jsonify(error="Authentication required"), 401
		return function(*args, **kwargs)
	return wrapped


@app.route("/")
def index():
	return render_template("index.html")


@app.get("/api/auth/me")
def current_user():
	if "user_id" not in session:
		return jsonify(user=None)
	row = get_db().execute("SELECT id, name, email FROM users WHERE id = ?", (session["user_id"],)).fetchone()
	if row is None:
		session.clear()
		return jsonify(user=None)
	return jsonify(user=dict(row))


@app.post("/api/auth/register")
def register():
	data = request.get_json(silent=True) or {}
	name, email, password = str(data.get("name", "")).strip(), str(data.get("email", "")).strip().lower(), str(data.get("password", ""))
	if not name or "@" not in email or len(password) < 8:
		return jsonify(error="Name, valid email, and an 8-character password are required"), 400
	db = get_db()
	try:
		cursor = db.execute("INSERT INTO users(name, email, password_hash, created_at) VALUES (?, ?, ?, ?)", (name, email, generate_password_hash(password), now_iso()))
		db.commit()
	except sqlite3.IntegrityError:
		return jsonify(error="An account with that email already exists"), 409
	session["user_id"] = cursor.lastrowid
	return jsonify(user={"id": cursor.lastrowid, "name": name, "email": email}), 201


@app.post("/api/auth/login")
def login():
	data = request.get_json(silent=True) or {}
	row = get_db().execute("SELECT * FROM users WHERE email = ?", (str(data.get("email", "")).strip().lower(),)).fetchone()
	if row is None or not check_password_hash(row["password_hash"], str(data.get("password", ""))):
		return jsonify(error="Email or password is incorrect"), 401
	session["user_id"] = row["id"]
	return jsonify(user={"id": row["id"], "name": row["name"], "email": row["email"]})


@app.post("/api/auth/logout")
def logout():
	session.clear()
	return jsonify(ok=True)


@app.get("/api/doctors")
def doctors():
	search = request.args.get("search", "").strip()
	query, params = "SELECT id, name, specialty, consultation_fee FROM doctors", []
	if search:
		query += " WHERE name LIKE ? OR specialty LIKE ?"
		params = [f"%{search}%", f"%{search}%"]
	rows = get_db().execute(query + " ORDER BY name", params).fetchall()
	return jsonify(items=[dict(row) for row in rows])


@app.get("/api/appointments")
@require_login
def appointments():
	db, where, params = get_db(), ["1 = 1", "a.status = 'booked'"], []
	if request.args.get("search", "").strip():
		term = f"%{request.args['search'].strip()}%"; where.append("(a.patient_name LIKE ? OR d.name LIKE ?)"); params.extend([term, term])
	if request.args.get("date", "").strip():
		where.append("substr(a.start_at, 1, 10) = ?"); params.append(request.args["date"].strip())
	allowed_sort = {"start_at": "a.start_at", "patient_name": "a.patient_name", "doctor": "d.name"}
	sort = allowed_sort.get(request.args.get("sort", "start_at"), "a.start_at"); direction = "DESC" if request.args.get("order", "asc").lower() == "desc" else "ASC"
	try:
		page, per_page = max(1, int(request.args.get("page", 1))), min(100, max(1, int(request.args.get("per_page", 10))))
	except ValueError:
		return jsonify(error="page and per_page must be integers"), 400
	where_sql = " AND ".join(where)
	count = db.execute(f"SELECT COUNT(*) FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE {where_sql}", params).fetchone()[0]
	rows = db.execute(f"SELECT a.*, d.name AS doctor_name, d.specialty FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE {where_sql} ORDER BY {sort} {direction} LIMIT ? OFFSET ?", [*params, per_page, (page - 1) * per_page]).fetchall()
	return jsonify(items=[appointment_json(row) for row in rows], page=page, per_page=per_page, total=count)


@app.post("/api/appointments")
@require_login
def create_appointment():
	data = request.get_json(silent=True) or {}
	try:
		doctor_id, start, end = int(data["doctor_id"]), parse_datetime(data["start_at"]), parse_datetime(data["end_at"])
		patient_name, patient_email = str(data["patient_name"]).strip(), str(data.get("patient_email", "")).strip()
	except (KeyError, TypeError, ValueError):
		return jsonify(error="Doctor, patient name, start time, and end time are required"), 400
	if not patient_name or start >= end:
		return jsonify(error="Patient name and a valid time range are required"), 400
	db = get_db()
	try:
		db.execute("BEGIN IMMEDIATE")
		doctor = db.execute("SELECT id, consultation_fee FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
		if doctor is None:
			db.rollback(); return jsonify(error="Doctor not found"), 404
		conflict = db.execute("SELECT 1 FROM appointments WHERE doctor_id = ? AND status = 'booked' AND start_at < ? AND end_at > ?", (doctor_id, end.isoformat(), start.isoformat())).fetchone()
		if conflict is not None:
			db.rollback(); return jsonify(error="That doctor is already booked for the selected time"), 409
		booking_fee = float(data.get("booking_fee", BOOKING_FEE))
		if booking_fee < 0:
			db.rollback(); return jsonify(error="Booking fee cannot be negative"), 400
		total = doctor["consultation_fee"] + booking_fee
		cursor = db.execute("INSERT INTO appointments(doctor_id, patient_name, patient_email, start_at, end_at, consultation_fee, booking_fee, total_amount, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (doctor_id, patient_name, patient_email, start.isoformat(), end.isoformat(), doctor["consultation_fee"], booking_fee, total, session["user_id"], now_iso()))
		db.commit()
	except sqlite3.Error:
		db.rollback(); return jsonify(error="Could not save the appointment"), 500
	row = db.execute("SELECT a.*, d.name AS doctor_name, d.specialty FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE a.id = ?", (cursor.lastrowid,)).fetchone()
	return jsonify(appointment=appointment_json(row)), 201


@app.post("/api/appointments/<int:appointment_id>/cancel")
@require_login
def cancel_appointment(appointment_id: int):
	db, data = get_db(), request.get_json(silent=True) or {}
	cancelled_by = str(data.get("cancelled_by", "patient")).lower()
	if cancelled_by not in {"patient", "doctor", "desk"}:
		return jsonify(error="cancelled_by must be patient, doctor, or desk"), 400
	row = db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
	if row is None: return jsonify(error="Appointment not found"), 404
	if row["status"] == "cancelled": return jsonify(error="Appointment is already cancelled"), 409
	fee = LATE_CANCELLATION_FEE if cancelled_by == "patient" and datetime.now(timezone.utc) > parse_datetime(row["start_at"]) - CANCELLATION_NOTICE else 0
	patient_charge = row["total_amount"] * 0.15 if cancelled_by == "patient" else 0
	refund = row["total_amount"] if cancelled_by == "doctor" else max(0, row["total_amount"] - patient_charge - fee)
	db.execute("UPDATE appointments SET status = 'cancelled', cancellation_fee = ?, refund_amount = ?, cancelled_by = ?, cancellation_reason = ? WHERE id = ?", (fee, refund, cancelled_by, data.get("reason", ""), appointment_id)); db.commit()
	return jsonify(cancelled=True, cancellation_fee=fee, refund_amount=refund, patient_cancellation_charge=patient_charge, late=fee > 0)


@app.post("/api/appointments/<int:appointment_id>/reschedule")
@require_login
def reschedule_appointment(appointment_id: int):
	data, db = request.get_json(silent=True) or {}, get_db(); row = db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
	if row is None or row["status"] != "booked": return jsonify(error="Only an active appointment can be rescheduled"), 404
	if row["reschedule_count"] >= 2: return jsonify(error="This appointment has already used both reschedule chances"), 409
	try: start, end = parse_datetime(data["start_at"]), parse_datetime(data["end_at"])
	except (KeyError, TypeError, ValueError): return jsonify(error="A new start and end time are required"), 400
	if start >= end: return jsonify(error="The new time range is invalid"), 400
	try:
		db.execute("BEGIN IMMEDIATE")
		conflict = db.execute("SELECT 1 FROM appointments WHERE doctor_id = ? AND status = 'booked' AND id != ? AND start_at < ? AND end_at > ?", (row["doctor_id"], appointment_id, end.isoformat(), start.isoformat())).fetchone()
		if conflict: db.rollback(); return jsonify(error="That doctor is already booked for the new time"), 409
		db.execute("UPDATE appointments SET start_at = ?, end_at = ?, reschedule_count = reschedule_count + 1 WHERE id = ?", (start.isoformat(), end.isoformat(), appointment_id)); db.commit()
	except sqlite3.Error:
		db.rollback(); return jsonify(error="Could not reschedule the appointment"), 500
	return jsonify(rescheduled=True, appointment_id=appointment_id, reschedule_count=row["reschedule_count"] + 1)


@app.get("/api/medicines")
@require_login
def medicines():
	rows = get_db().execute("SELECT id, name, strength, price, stock FROM medicines WHERE stock > 0 ORDER BY name").fetchall()
	return jsonify(items=[dict(row) for row in rows])


@app.post("/api/prescriptions")
@require_login
def create_prescription():
	data = request.get_json(silent=True) or {}
	try: appointment_id, doctor_id, file_name, note = int(data["appointment_id"]), int(data["doctor_id"]), str(data["file_name"]).strip(), str(data["verification_note"]).strip()
	except (KeyError, TypeError, ValueError): return jsonify(error="Appointment, doctor, prescription file name, and signed/stamped verification are required"), 400
	if not file_name or not note or not any(word in note.lower() for word in ("signed", "stamped")): return jsonify(error="Confirm that the prescription is signed or stamped by the doctor"), 400
	db = get_db(); cursor = db.execute("INSERT INTO prescriptions(appointment_id, doctor_id, patient_name, file_name, verification_note, verified_at, created_by) SELECT ?, ?, patient_name, ?, ?, ?, ? FROM appointments WHERE id = ?", (appointment_id, doctor_id, file_name, note, now_iso(), session["user_id"], appointment_id))
	if cursor.rowcount == 0: return jsonify(error="Appointment not found"), 404
	db.commit(); return jsonify(prescription_id=cursor.lastrowid, verified=True), 201


@app.post("/api/medicine-counter")
@require_login
def medicine_counter():
	data = request.get_json(silent=True) or {}
	try: appointment_id, prescription_id, medicine_id, quantity = int(data["appointment_id"]), int(data["prescription_id"]), int(data["medicine_id"]), int(data.get("quantity", 1))
	except (KeyError, TypeError, ValueError): return jsonify(error="Appointment, verified prescription, medicine, and quantity are required"), 400
	if quantity < 1: return jsonify(error="Quantity must be at least one"), 400
	db = get_db(); verified = db.execute("SELECT id FROM prescriptions WHERE id = ? AND appointment_id = ?", (prescription_id, appointment_id)).fetchone(); medicine = db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
	if not verified: return jsonify(error="A prescription signed or stamped by a doctor is required first"), 400
	if not medicine or medicine["stock"] < quantity: return jsonify(error="Medicine is unavailable in the requested quantity"), 409
	amount = medicine["price"] * quantity; db.execute("UPDATE medicines SET stock = stock - ? WHERE id = ?", (quantity, medicine_id)); db.execute("INSERT INTO medicine_orders(appointment_id, prescription_id, medicine_id, quantity, amount, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (appointment_id, prescription_id, medicine_id, quantity, amount, session["user_id"], now_iso())); db.commit()
	return jsonify(ordered=True, amount=amount, currency="INR")


with app.app_context():
	init_db()

if __name__ == "__main__":
	port = int(os.environ.get("PORT", "5001"))
	app.run(debug=True, host="0.0.0.0", port=port)

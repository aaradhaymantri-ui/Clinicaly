const state = { page: 1, perPage: 6, sort: 'start_at', search: '', date: '' };
const $ = (selector) => document.querySelector(selector);
const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Something went wrong');
  return data;
}

function showMessage(target, message, good = false) {
  target.textContent = message;
  target.className = `form-message ${good ? 'good' : 'error'}`;
}

function setSignedIn(user) {
  $('#auth-panel').classList.toggle('hidden', Boolean(user));
  $('#dashboard').classList.toggle('hidden', !user);
  $('#user-area').innerHTML = user ? `<span class="user-name">${user.name}</span><button class="button button-quiet" id="logout">Log out</button>` : '';
  if (user) {
    $('#logout').onclick = async () => { await api('/api/auth/logout', { method: 'POST' }); setSignedIn(null); };
    loadDoctors();
    loadAppointments();
  }
}

async function loadDoctors() {
  const data = await api('/api/doctors');
  $('#doctor-select').innerHTML = data.items.map((doctor) => `<option value="${doctor.id}" data-specialty="${doctor.specialty}" data-fee="${doctor.consultation_fee}">${doctor.name} · ${doctor.specialty} · ${currency.format(doctor.consultation_fee)}</option>`).join('');
  setClinicTheme();
}

function setClinicTheme() {
  const specialty = $('#doctor-select').selectedOptions[0]?.dataset.specialty || 'General medicine';
  const theme = specialty.toLowerCase().includes('dent') ? 'dentistry' : specialty.toLowerCase().includes('pediatric') ? 'pediatrics' : specialty.toLowerCase().includes('internal') ? 'internal-medicine' : 'general-medicine';
  document.body.dataset.clinicTheme = theme;
  $('#theme-label').textContent = specialty;
  $('#theme-icon').textContent = theme === 'dentistry' ? '🦷' : theme === 'pediatrics' ? '🩺' : theme === 'general-medicine' ? '💊' : '＋';
  const fee = Number($('#doctor-select').selectedOptions[0]?.dataset.fee || 0);
  $('#fee-preview').textContent = `Consultation ${currency.format(fee)} + booking ₹50 = ${currency.format(fee + 50)}`;
}

function appointmentCard(item) {
  const start = new Date(item.start_at);
  const end = new Date(item.end_at);
  const date = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const time = `${start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} – ${end.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  return `<article class="appointment-row"><div class="appointment-time"><b>${time}</b><span>${date}</span></div><div class="appointment-person"><b>${item.patient_name}</b><span>${item.doctor} · ${item.specialty}</span></div><div class="appointment-contact"><b>${currency.format(item.total_amount)}</b><span>${item.patient_email || 'No email'}</span></div><div class="row-actions"><button class="cancel-link" data-cancel="${item.id}">Cancel</button><button class="cancel-link" data-reschedule="${item.id}">Move</button></div></article>`;
}

async function loadAppointments() {
  const query = new URLSearchParams({ page: state.page, per_page: state.perPage, sort: state.sort, search: state.search, date: state.date });
  try {
    const data = await api(`/api/appointments?${query}`);
    $('#appointments').innerHTML = data.items.length ? data.items.map(appointmentCard).join('') : '<div class="empty-state"><span>○</span><b>No appointments found</b><p>Try another search or book a new visit.</p></div>';
    $('#result-count').textContent = `${data.total} ${data.total === 1 ? 'visit' : 'visits'}`;
    $('#page-label').textContent = `Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.per_page))}`;
    $('#previous-page').disabled = data.page <= 1;
    $('#next-page').disabled = data.page * data.per_page >= data.total;
    document.querySelectorAll('[data-cancel]').forEach((button) => { button.onclick = () => cancelAppointment(button.dataset.cancel); });
    document.querySelectorAll('[data-reschedule]').forEach((button) => { button.onclick = () => rescheduleAppointment(button.dataset.reschedule); });
  } catch (error) { $('#appointments').innerHTML = `<div class="empty-state"><b>${error.message}</b></div>`; }
}

async function cancelAppointment(id) {
  const actor = (window.prompt('Who cancelled this visit? Type patient or doctor.', 'patient') || 'patient').toLowerCase();
  if (!['patient', 'doctor'].includes(actor)) return window.alert('Please choose patient or doctor.');
  if (!window.confirm(actor === 'doctor' ? 'Doctor cancellation gives the patient a 100% refund. Continue?' : 'Patient cancellation retains 15% of the total, plus any late fee. Continue?')) return;
  try { const result = await api(`/api/appointments/${id}/cancel`, { method: 'POST', body: JSON.stringify({ cancelled_by: actor }) }); window.alert(`${actor === 'doctor' ? 'Full refund' : 'Patient cancellation charge'}: ${currency.format(actor === 'doctor' ? result.refund_amount : result.patient_cancellation_charge)}`); loadAppointments(); } catch (error) { window.alert(error.message); }
}

async function rescheduleAppointment(id) {
  const start = window.prompt('New start time (ISO format, e.g. 2026-09-20T10:00:00+05:30):');
  const end = window.prompt('New end time (ISO format):');
  if (!start || !end) return;
  try { const result = await api(`/api/appointments/${id}/reschedule`, { method: 'POST', body: JSON.stringify({ start_at: start, end_at: end }) }); window.alert(`Moved successfully. Reschedule ${result.reschedule_count} of 2 used.`); loadAppointments(); } catch (error) { window.alert(error.message); }
}

$('#auth-form').onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try { const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ email: form.get('email'), password: form.get('password') }) }); setSignedIn(data.user); } catch (error) { showMessage($('#auth-message'), error.message); }
};

$('#register-button').onclick = async () => {
  const form = new FormData($('#auth-form'));
  try { const data = await api('/api/auth/register', { method: 'POST', body: JSON.stringify({ name: form.get('name'), email: form.get('email'), password: form.get('password') }) }); setSignedIn(data.user); } catch (error) { showMessage($('#auth-message'), error.message); }
};

$('#booking-form').onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try { await api('/api/appointments', { method: 'POST', body: JSON.stringify(Object.fromEntries(form)) }); showMessage($('#booking-message'), 'Appointment booked.', true); event.target.reset(); $('#booking-panel').classList.add('hidden'); loadAppointments(); } catch (error) { showMessage($('#booking-message'), error.message); }
};

$('#new-appointment').onclick = () => $('#booking-panel').classList.remove('hidden');
$('#close-booking').onclick = () => $('#booking-panel').classList.add('hidden');
$('#doctor-select').onchange = setClinicTheme;

$('#prescription-form').onsubmit = async (event) => {
  event.preventDefault();
  try {
    const data = await api('/api/prescriptions', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) });
    $('#medicine-form').classList.remove('hidden');
    $('#medicine-form [name="prescription_id"]').value = data.prescription_id;
    const medicines = await api('/api/medicines');
    $('#medicine-select').innerHTML = medicines.items.map((item) => `<option value="${item.id}">${item.name} · ${item.strength} · ${currency.format(item.price)}</option>`).join('');
    showMessage($('#prescription-message'), 'Prescription verified. You can dispense medicines.', true);
  } catch (error) { showMessage($('#prescription-message'), error.message); }
};

$('#medicine-form').onsubmit = async (event) => {
  event.preventDefault();
  try {
    const result = await api('/api/medicine-counter', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) });
    showMessage($('#medicine-message'), `Added to bill: ${currency.format(result.amount)}`, true);
  } catch (error) { showMessage($('#medicine-message'), error.message); }
};
$('#search').oninput = (event) => { state.search = event.target.value; state.page = 1; loadAppointments(); };
$('#day-filter').onchange = (event) => { state.date = event.target.value; state.page = 1; loadAppointments(); };
$('#sort').onchange = (event) => { state.sort = event.target.value; state.page = 1; loadAppointments(); };
$('#previous-page').onclick = () => { state.page -= 1; loadAppointments(); };
$('#next-page').onclick = () => { state.page += 1; loadAppointments(); };
document.querySelectorAll('[data-scroll]').forEach((button) => { button.onclick = () => document.querySelector(button.dataset.scroll).scrollIntoView({ behavior: 'smooth' }); });

api('/api/auth/me').then((data) => setSignedIn(data.user));

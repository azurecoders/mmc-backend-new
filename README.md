# Hospital Management System - Backend

Production-grade, asynchronous FastAPI backend with dynamic Role-Based Access Control (RBAC), hierarchical sub-roles, and granular permission management.

## Key Features

1. **Fully Dynamic RBAC & Permission System**:
   - Zero hardcoded role enums. New roles and sub-roles can be created dynamically via API.
   - **Hierarchical Sub-roles**: A sub-role (e.g. `CARDIOLOGIST`) can define a `parent_role_id` (e.g. `DOCTOR`), automatically inheriting all permissions from parent roles recursively.
   - **Granular Permissions**: Domain-action scoped permissions (e.g. `appointments:create`, `queue:manage`, `prescriptions:dispense`, `lab:upload_result`).
   - **Wildcard Support**: `SUPER_ADMIN` has wildcard `*` permission bypassing checks.

2. **Core System Roles (Pre-seeded)**:
   - `SUPER_ADMIN`: Hospital administrator with full administrative access (`*`).
   - `DOCTOR`: Examines patients, writes diagnoses/notes, prescribes medications, orders lab tests.
   - `COMPOUNDER`: Manages live queues, verifies appointments, records pre-consultation vitals, registers walk-in patients.
   - `LAB_ASSISTANT`: Manages lab orders, uploads diagnostic test results.
   - `PHARMACIST`: Views prescriptions and dispenses medication.
   - `PATIENT`: Books appointments, views queue status, accesses prescriptions and lab reports.

3. **Authentication & Session Security**:
   - Passwords hashed using `bcrypt`.
   - Dual-token architecture (Short-lived Access Token + Long-lived Refresh Token).
   - **Refresh Token Rotation & Revocation**: Prevents replay attacks and supports multi-device session invalidation on logout or password change.
   - Login supports both **Email** and **Phone Number**.

## API Endpoints

### Authentication (`/api/v1/auth`)
- `POST /register`: Patient self-registration (assigns `PATIENT` role by default).
- `POST /login`: Login using email or phone + password. Returns JWT tokens, profile, roles, and effective permissions.
- `POST /refresh`: Exchange valid refresh token for a new access token (with token rotation).
- `POST /logout`: Revoke active session and refresh token.
- `GET /me`: Get current authenticated user profile, roles, and calculated permissions.
- `POST /change-password`: Change password and revoke existing sessions.

### Roles & Sub-roles (`/api/v1/roles`)
- `GET /`: List all roles, sub-roles, and effective permissions (`roles:read`).
- `POST /`: Create a new role or sub-role with optional `parent_role_id` (`roles:create`).
- `GET /{role_id}`: Get role details with resolved inherited permissions (`roles:read`).
- `PUT /{role_id}`: Update role name, description, parent, or assigned permissions (`roles:update`).
- `DELETE /{role_id}`: Delete custom non-system role (`roles:delete`).

### Permissions (`/api/v1/permissions`)
- `GET /`: List all system permissions, filterable by module (`permissions:read`).
- `POST /`: Dynamically define a new system permission (`permissions:create`).

### User Management (`/api/v1/users`)
- `GET /`: List users/staff with search and role filters (`users:read`).
- `POST /`: Create staff accounts with assigned roles (`users:create`).
- `GET /{user_id}`: Get user details and permissions (`users:read`).
- `PUT /{user_id}`: Update user profile (`users:update`).
- `PUT /{user_id}/roles`: Dynamically assign/update roles for any user (`roles:assign`).

### Appointments & AI Triage (`/api/v1/appointments`)
- `POST /recommend-doctors`: **AI Doctor & Department Recommendation** using `gemma-4-31b-it` (Google AI Studio) based on patient symptoms, duration, and severity. Returns recommended department, clinical triage summary, and matching doctors with fees and match rationale.
- `POST /book-online`: Patient submits online booking request. Automatically issues a daily sequential token for the doctor and marks status as `PENDING_APPROVAL`.
- `POST /book-walkin`: Compounder on-the-spot registration for walk-in patients (auto-creates patient profile if new, assigns daily sequential token, marks status as `APPROVED`).
- `GET /`: List appointments (role-aware: patients view their own, doctors view their cabin queue, compounders/admins view all).
- `GET /pending-approvals`: Compounder view of appointments waiting for review (`appointments:approve`).
- `GET /{appointment_id}`: Full appointment details with patient, doctor, and compounder info.
- `POST /{appointment_id}/approve`: Compounder verifies and approves appointment (`appointments:approve`).
- `POST /{appointment_id}/reject`: Compounder rejects appointment with reason (`appointments:approve`).
- `POST /{appointment_id}/cancel`: Patient or doctor cancels appointment (`appointments:cancel`).

### Departments (`/api/v1/departments`)
- `GET /`: List active hospital departments.
- `POST /`: Create hospital department (`users:create`).
- `GET /{department_id}`: Get department details.
- `PUT /{department_id}`: Update department.

### Doctors & Schedules (`/api/v1/doctors`)
- `GET /`: Directory of doctors with qualifications, consultation fees, room numbers, and schedules.
- `POST /`: Onboard doctor profile with initial schedules (`users:create`).
- `GET /{doctor_id}`: Doctor profile and weekly working schedules.
- `PUT /{doctor_id}`: Update doctor profile (`users:update`).
- `POST /{doctor_id}/schedules`: Add weekly schedule slot (`users:update`).

### Real-Time Live Queue Engine (`/api/v1/queue`)
- `POST /check-in`: Compounder checks in an approved appointment into today's queue (`queue:manage`). Emits real-time queue update.
- `POST /call-patient`: Compounder or doctor activates patient turn (`queue:call_patient`). Instantly emits `queue:your_turn` event to the patient's device and doctor cabin.
- `POST /{queue_entry_id}/start-session`: Doctor begins consultation (`consultations:create`).
- `POST /{queue_entry_id}/complete-session`: Doctor finishes consultation (`consultations:update`).
- `POST /{queue_entry_id}/hold`: Put patient on hold (`queue:manage`).
- `GET /patient-status/{appointment_id}`: Patient's live tracker: token number, currently serving token, count of patients ahead, and dynamic estimated wait time.
- `GET /doctor-queue/{doctor_id}`: Doctor's cabin queue dashboard for today.
- `GET /tv-display`: Public feed for Waiting Room wall TV monitors.

### Doctor Consultations & Prescriptions (`/api/v1/consultations`)
- `POST /`: Doctor records clinical consultation with chief complaint, symptoms, diagnosis, clinical notes, special instructions, red-flag highlights, structured prescriptions, and lab orders (`consultations:create`).
  - Automatically finalizes visit and notifies:
    - **Patient**: receives prescription and instructions.
    - **Pharmacy**: notified with medicines to prepare/dispense.
    - **Lab**: notified with diagnostic tests to process.
    - **Queue**: marks visit as `COMPLETED`.
- `GET /{consultation_id}`: View full consultation details (`consultations:read`).
- `GET /appointment/{appointment_id}`: Patient or doctor views consultation for a specific appointment (`consultations:read`).
- `GET /patient/{patient_id}/history`: Full medical history of past visits and prescriptions (`consultations:read`).
- `PUT /{consultation_id}`: Update consultation notes (`consultations:update`).

### Pharmacy & Medication Inventory (`/api/v1/pharmacy`)
- `GET /inventory`: Pharmacist views medication catalog, stock levels, generic names, unit prices, and low stock warnings (`pharmacy:read_inventory`).
- `POST /inventory`: Pharmacist adds new medicine to inventory with category, unit price, stock quantity, and reorder levels (`pharmacy:manage_inventory`).
- `PUT /inventory/{medicine_id}`: Pharmacist updates stock levels, unit pricing, or active status (`pharmacy:manage_inventory`).
- `GET /prescriptions`: Real-time queue of incoming prescriptions from finalized doctor consultations (`prescriptions:read`).
- `POST /dispense`: Pharmacist confirms dispensation of prescription items (`pharmacy:dispense`). Supports:
  - Automatic inventory stock decrement.
  - Generic brand substitutions with pharmacist clinical notes.
  - Out of stock tracking.
  - Automatic real-time notification to patient device (`pharmacy:prescription_dispensed`) specifying the pickup counter.

### Laboratory & Diagnostics (`/api/v1/lab`)
- `GET /catalog`: Hospital catalog of available diagnostic tests (CBC, Lipid Profile, Chest X-ray, ECG, etc.).
- `POST /catalog`: Lab Assistant adds new diagnostic test to catalog (`lab:manage_catalog`).
- `GET /orders`: List pending and completed lab orders across patients and doctors (`lab:read_orders`).
- `GET /orders/{order_id}`: View order details, diagnostic status, and completed test findings (`lab:read_orders`).
- `POST /orders/{order_id}/collect-sample`: Lab Assistant marks diagnostic sample collected with timestamp (`lab:upload_result`).
- `POST /orders/{order_id}/submit-result`: Lab Assistant enters test findings, structured JSON values, abnormal indicators, critical alerts, and report URLs (`lab:upload_result`).
  - Automatically transitions order status to `COMPLETED`.
  - Dispatches instant real-time notification (`lab:report_completed`) to both Patient and Doctor.

### Patient Medical Profiles & History Archive (`/api/v1/patients`)
- `GET /me/medical-profile`: Patient views their own comprehensive medical history archive (biometrics, chronic conditions, drug allergies, past surgeries, active medications, family history, and lifestyle factors).
- `PUT /me/medical-profile`: Patient updates their medical history archive.
- `GET /{patient_id}/medical-profile`: Clinicians (Doctors & Compounders) inspect the patient's complete medical history (`vitals:read`, `consultations:read`).

### Vitals Logging & AI Early Warning Triage (`/api/v1/vitals`)
- `POST /patient-log`: Patient self-reports vitals from the patient portal (Blood Pressure, Heart Rate, SpO2, Respiratory Rate, Temperature, Glucose, AVPU).
  - Evaluates vitals using clinical **MEWS (Modified Early Warning Score)** and **NEWS2** algorithms.
  - **AI Contextual Analysis (`gemma-4-31b-it`)**: Correlates vital signs against the patient's detailed medical history (e.g. chronic CAD, prior stents, diabetes, active medications).
  - **Emergency Doctor Escalation**: If critical, automatically locates the patient's primary consultant physician and emits a high-priority real-time Socket.IO alert (`patient:critical_vitals_alert`).
- `POST /compounder-intake`: Compounder enters vitals during clinic triage/check-in (`vitals:create`).
  - Computes MEWS/NEWS scores and checks medical history.
  - **Automatic Queue Escalation**: If the patient is in critical distress, automatically flips the queue token to `is_priority = True` and broadcasts `queue:emergency_priority` to cabin screens.
- `GET /patient/{patient_id}/history`: View vitals timeline and historical MEWS trends (`vitals:read`).
- `GET /doctor/critical-alerts`: Doctor views incoming critical vitals alerts assigned to them (`consultations:read`).
- `POST /alerts/{vitals_log_id}/acknowledge`: Doctor marks critical alert as reviewed and acknowledged.

### Real-Time Socket.IO Channels (`/socket.io`)
- **Transport**: Native WebSocket & polling via `python-socketio` ASGI integration.
- **Rooms**:
  - `queue:tv`: Public waiting room screen feed.
  - `doctor:{doctor_id}`: Cabin-specific doctor alerts.
  - `patient:{patient_id}`: Patient personal notifications.
  - `appointment:{appointment_id}`: Live token tracking room.
  - `compounder:queue`: All compounders managing active queues.
  - `pharmacy:orders`: Real-time prescription orders stream for pharmacists.
  - `lab:orders`: Real-time diagnostic test orders stream for lab assistants.
- **Key Events**:
  - `queue:your_turn`: Instant alert to patient and doctor when turn is called.
  - `queue:tv_updated`: Live refresh of wall-mounted TV cabin displays.
  - `queue:doctor_updated`: Live queue count updates in doctor cabin.
  - `queue:patient_status`: Personalized wait-time, progress, and priority status updates.
  - `queue:emergency_priority`: Urgent priority token escalation alert for compounders and doctors.
  - `consultation:finalized`: Instant prescription & note delivery to patient device.
  - `pharmacy:new_prescription`: Real-time order dispatch to pharmacy dispensing desk.
  - `pharmacy:prescription_dispensed`: Real-time pickup notification to patient device with counter location.
  - `lab:new_orders`: Real-time diagnostic test order dispatch to laboratory assistants.
  - `lab:report_completed`: Real-time diagnostic report readiness notification to patient and doctor.
  - `patient:critical_vitals_alert`: Emergency alert dispatched directly to attending consultant when self-reported vitals indicate acute physiological distress.

## Running Locally

```bash
# 1. Activate virtual environment (or create with python -m venv .venv)
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run Database Migrations
alembic upgrade head

# 4. Start Development Server (FastAPI + Socket.IO)
uvicorn app.main:socket_app --reload --port 8000
```

- Interactive Swagger Docs: `http://localhost:8000/api/v1/docs`
- ReDoc: `http://localhost:8000/api/v1/redoc`

## Running Tests

```bash
pytest -v -W ignore
```

from fastapi import APIRouter
from app.api.v1.endpoints import (
    appointments,
    auth,
    consultations,
    departments,
    doctors,
    lab,
    patients,
    permissions,
    pharmacy,
    queue,
    roles,
    users,
    vitals,
    emergency,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(roles.router, prefix="/roles", tags=["Roles & Sub-roles"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["Permissions"])
api_router.include_router(users.router, prefix="/users", tags=["User Management"])
api_router.include_router(departments.router, prefix="/departments", tags=["Departments"])
api_router.include_router(doctors.router, prefix="/doctors", tags=["Doctors & Schedules"])
api_router.include_router(appointments.router, prefix="/appointments", tags=["Appointments & AI Triage"])
api_router.include_router(queue.router, prefix="/queue", tags=["Live Queue Engine"])
api_router.include_router(consultations.router, prefix="/consultations", tags=["Doctor Consultations & Prescriptions"])
api_router.include_router(lab.router, prefix="/lab", tags=["Laboratory & Diagnostics"])
api_router.include_router(pharmacy.router, prefix="/pharmacy", tags=["Pharmacy & Medication Dispensing"])
api_router.include_router(patients.router, prefix="/patients", tags=["Patient Medical Profiles & History"])
api_router.include_router(vitals.router, prefix="/vitals", tags=["Vitals Logging & AI Triage Scoring"])
api_router.include_router(emergency.router, prefix="/emergency", tags=["Emergency Color Codes & Teams"])

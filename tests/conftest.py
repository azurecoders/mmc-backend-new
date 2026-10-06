import pytest_asyncio
from sqlalchemy import select, delete
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.department import Department
from app.models.doctor import DoctorProfile, DoctorSchedule
from app.models.role import Role
from app.models.user import User
from app.db.init_db import init_db

TEST_DOCTORS_SEED = [
    {
        "email": "dr.smith.cardio@hospital.com",
        "full_name": "Dr. Sarah Smith",
        "phone": "+19991112233",
        "dept_code": "CARDIOLOGY",
        "specialization": "Interventional Cardiologist",
        "qualifications": "MBBS, MD (Cardiology), FACC",
        "experience_years": 14,
        "consultation_fee": 75.0,
        "room_number": "Cabin 201, 2nd Floor",
    },
    {
        "email": "dr.patel.general@hospital.com",
        "full_name": "Dr. Rajesh Patel",
        "phone": "+19992223344",
        "dept_code": "GENERAL_MEDICINE",
        "specialization": "Senior Consultant Physician",
        "qualifications": "MBBS, MD (Internal Medicine)",
        "experience_years": 18,
        "consultation_fee": 50.0,
        "room_number": "Cabin 101, 1st Floor",
    },
    {
        "email": "dr.clark.ortho@hospital.com",
        "full_name": "Dr. Robert Clark",
        "phone": "+19993334455",
        "dept_code": "ORTHOPEDICS",
        "specialization": "Orthopedic & Spine Surgeon",
        "qualifications": "MBBS, MS (Ortho), FRCS",
        "experience_years": 12,
        "consultation_fee": 70.0,
        "room_number": "Cabin 304, 3rd Floor",
    },
    {
        "email": "dr.lee.derma@hospital.com",
        "full_name": "Dr. Amanda Lee",
        "phone": "+19994445566",
        "dept_code": "DERMATOLOGY",
        "specialization": "Dermatologist & Allergiologist",
        "qualifications": "MBBS, MD (Dermatology)",
        "experience_years": 9,
        "consultation_fee": 60.0,
        "room_number": "Cabin 105, 1st Floor",
    },
]

TEST_STAFF_SEEDS = [
    {"email": "compounder@hospital.com", "phone": "+10000000001", "name": "Hospital Reception Compounder", "role": "COMPOUNDER", "pass": "Compounder@123"},
    {"email": "pharmacist@hospital.com", "phone": "+10000000002", "name": "Head Pharmacist", "role": "PHARMACIST", "pass": "Pharmacist@123"},
    {"email": "lab@hospital.com", "phone": "+10000000003", "name": "Senior Lab Pathologist", "role": "LAB_ASSISTANT", "pass": "Lab@123456"},
    {"email": "nurse@hospital.com", "phone": "+10000000004", "name": "Head Nurse Sarah Jenkins, RN", "role": "NURSE", "pass": "Nurse@123"},
]

@pytest_asyncio.fixture(autouse=True, scope="session")
async def provision_test_environment():
    """
    Provisions staff and doctors strictly during test execution,
    then purges them at teardown to keep the live DB pristine.
    """
    async with AsyncSessionLocal() as session:
        # Initialize schema, roles, and emergency groups
        await init_db(session)

        # Load roles
        roles_res = await session.execute(select(Role))
        roles_map = {r.code: r for r in roles_res.scalars().all()}

        # Load departments
        depts_res = await session.execute(select(Department))
        dept_map = {d.code: d for d in depts_res.scalars().all()}

        # 1. Provision staff
        for staff in TEST_STAFF_SEEDS:
            stmt = select(User).where(User.email == staff["email"])
            user_obj = (await session.execute(stmt)).scalar_one_or_none()
            if not user_obj:
                r_obj = roles_map.get(staff["role"])
                new_staff = User(
                    email=staff["email"],
                    phone=staff["phone"],
                    full_name=staff["name"],
                    hashed_password=hash_password(staff["pass"]),
                    is_active=True,
                    is_verified=True,
                    roles=[r_obj] if r_obj else [],
                )
                session.add(new_staff)

        # 2. Provision doctors
        doc_role = roles_map.get("DOCTOR")
        for doc_seed in TEST_DOCTORS_SEED:
            stmt = select(User).where(User.email == doc_seed["email"])
            doc_user = (await session.execute(stmt)).scalar_one_or_none()
            if not doc_user:
                doc_user = User(
                    email=doc_seed["email"],
                    phone=doc_seed["phone"],
                    full_name=doc_seed["full_name"],
                    hashed_password=hash_password("Doctor@123456"),
                    is_active=True,
                    is_verified=True,
                    roles=[doc_role] if doc_role else [],
                )
                session.add(doc_user)
                await session.flush()

            stmt = select(DoctorProfile).where(DoctorProfile.user_id == doc_user.id)
            doc_profile = (await session.execute(stmt)).scalar_one_or_none()
            dept = dept_map.get(doc_seed["dept_code"])
            if not doc_profile and dept:
                doc_profile = DoctorProfile(
                    user_id=doc_user.id,
                    department_id=dept.id,
                    specialization=doc_seed["specialization"],
                    qualifications=doc_seed["qualifications"],
                    experience_years=doc_seed["experience_years"],
                    consultation_fee=doc_seed["consultation_fee"],
                    room_number=doc_seed["room_number"],
                    is_available=True,
                    avg_consultation_mins=15,
                )
                session.add(doc_profile)
                await session.flush()

                for day in range(5):
                    sch = DoctorSchedule(
                        doctor_id=doc_profile.id,
                        day_of_week=day,
                        start_time="09:00",
                        end_time="17:00",
                        max_daily_patients=35,
                        is_active=True,
                    )
                    session.add(sch)

        await session.commit()

    yield

    # Teardown: purge everything except superadmin to leave the DB completely clean!
    async with AsyncSessionLocal() as session:
        from app.models.lab import LabResult, LabOrder
        from app.models.emergency import EmergencyAlertResponder, EmergencyAlert
        from app.models.pharmacy import MedicineDispenseRecord
        from app.models.consultation import PrescriptionItem, Consultation
        from app.models.patient import PatientVitalsLog, PatientMedicalProfile
        from app.models.queue import QueueEntry
        from app.models.appointment import Appointment
        from app.models.token import RefreshToken

        await session.execute(delete(EmergencyAlertResponder))
        await session.execute(delete(EmergencyAlert))
        await session.execute(delete(LabResult))
        await session.execute(delete(LabOrder))
        await session.execute(delete(MedicineDispenseRecord))
        await session.execute(delete(PrescriptionItem))
        await session.execute(delete(Consultation))
        await session.execute(delete(PatientVitalsLog))
        await session.execute(delete(PatientMedicalProfile))
        await session.execute(delete(QueueEntry))
        await session.execute(delete(Appointment))
        await session.execute(delete(DoctorSchedule))
        await session.execute(delete(DoctorProfile))
        await session.execute(delete(RefreshToken))

        admin_email = settings.FIRST_SUPERADMIN_EMAIL.lower().strip()
        await session.execute(delete(User).where(User.email != admin_email))
        await session.commit()

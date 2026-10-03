from app.crud.crud_permission import crud_permission
from app.crud.crud_role import crud_role
from app.crud.crud_user import crud_user
from app.crud.crud_token import crud_token
from app.crud.crud_department import crud_department
from app.crud.crud_doctor import crud_doctor
from app.crud.crud_appointment import crud_appointment
from app.crud.crud_queue import crud_queue
from app.crud.crud_consultation import crud_consultation
from app.crud.crud_lab import crud_lab
from app.crud.crud_pharmacy import crud_pharmacy

__all__ = [
    "crud_permission",
    "crud_role",
    "crud_user",
    "crud_token",
    "crud_department",
    "crud_doctor",
    "crud_appointment",
    "crud_queue",
    "crud_consultation",
    "crud_lab",
    "crud_pharmacy",
]

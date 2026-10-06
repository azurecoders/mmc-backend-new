import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.core.socket_manager import sio
from app.crud.crud_emergency import crud_emergency
from app.models.user import User
from app.schemas.emergency import (
    EmergencyCodeGroupResponse,
    EmergencyGroupMemberAddRequest,
    EmergencyTriggerRequest,
    EmergencyAlertResponse,
    EmergencyAcknowledgeRequest,
    EmergencyResolveRequest,
    UserBrief,
    EmergencyResponderResponse,
)

router = APIRouter()

STANDARD_HOSPITAL_WARDS = [
    "ICU — Intensive Care Unit",
    "CCU — Coronary Care Unit",
    "Emergency & Trauma Bay",
    "General Ward — Floor 1",
    "General Ward — Floor 2",
    "General Ward — Floor 3",
    "Operation Theater (OT)",
    "Pediatric & Neonatal Ward",
    "Maternity & Labor Ward",
    "Cardiology Inpatient Ward",
    "OPD & Triage Reception Area",
]


@router.get(
    "/wards",
    response_model=List[str],
    summary="List standard hospital wards and clinical locations",
)
async def list_hospital_wards():
    return STANDARD_HOSPITAL_WARDS


@router.get(
    "/groups",
    response_model=List[EmergencyCodeGroupResponse],
    summary="List all emergency color code groups and their assigned responder teams",
    dependencies=[Depends(require_permissions(["emergency:read"]))],
)
async def list_emergency_groups(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    groups = await crud_emergency.get_groups(db)
    responses = []
    for g in groups:
        member_briefs = [
            UserBrief(
                id=m.id,
                email=m.email,
                full_name=m.full_name,
                phone=m.phone,
                role_names=[r.name for r in m.roles] if m.roles else [],
            )
            for m in g.members
        ]
        responses.append(
            EmergencyCodeGroupResponse(
                id=g.id,
                code=g.code,
                name=g.name,
                color_hex=g.color_hex,
                badge_color=g.badge_color,
                description=g.description,
                call_to_action=g.call_to_action,
                is_active=g.is_active,
                members=member_briefs,
                member_count=len(member_briefs),
            )
        )
    return responses


@router.post(
    "/groups/{group_code}/members",
    response_model=EmergencyCodeGroupResponse,
    summary="Super Admin assigns a staff member to an emergency color code group",
    dependencies=[Depends(require_permissions(["emergency:manage_groups"]))],
)
async def add_group_member(
    group_code: str,
    payload: EmergencyGroupMemberAddRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    group = await crud_emergency.get_group_by_code(db, group_code)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Emergency code group '{group_code}' not found.",
        )

    stmt = select(User).where(User.id == payload.user_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staff user not found.",
        )

    updated_group = await crud_emergency.add_member_to_group(db, group, user)
    member_briefs = [
        UserBrief(
            id=m.id,
            email=m.email,
            full_name=m.full_name,
            phone=m.phone,
            role_names=[r.name for r in m.roles] if m.roles else [],
        )
        for m in updated_group.members
    ]
    return EmergencyCodeGroupResponse(
        id=updated_group.id,
        code=updated_group.code,
        name=updated_group.name,
        color_hex=updated_group.color_hex,
        badge_color=updated_group.badge_color,
        description=updated_group.description,
        call_to_action=updated_group.call_to_action,
        is_active=updated_group.is_active,
        members=member_briefs,
        member_count=len(member_briefs),
    )


@router.delete(
    "/groups/{group_code}/members/{user_id}",
    response_model=EmergencyCodeGroupResponse,
    summary="Super Admin removes a staff member from an emergency color code group",
    dependencies=[Depends(require_permissions(["emergency:manage_groups"]))],
)
async def remove_group_member(
    group_code: str,
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    group = await crud_emergency.get_group_by_code(db, group_code)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Emergency code group '{group_code}' not found.",
        )

    stmt = select(User).where(User.id == user_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staff user not found.",
        )

    updated_group = await crud_emergency.remove_member_from_group(db, group, user)
    member_briefs = [
        UserBrief(
            id=m.id,
            email=m.email,
            full_name=m.full_name,
            phone=m.phone,
            role_names=[r.name for r in m.roles] if m.roles else [],
        )
        for m in updated_group.members
    ]
    return EmergencyCodeGroupResponse(
        id=updated_group.id,
        code=updated_group.code,
        name=updated_group.name,
        color_hex=updated_group.color_hex,
        badge_color=updated_group.badge_color,
        description=updated_group.description,
        call_to_action=updated_group.call_to_action,
        is_active=updated_group.is_active,
        members=member_briefs,
        member_count=len(member_briefs),
    )


@router.post(
    "/trigger",
    response_model=EmergencyAlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger an Emergency Color Code (Doctor, Nurse, Compounder)",
    dependencies=[Depends(require_permissions(["emergency:trigger"]))],
)
async def trigger_emergency_code(
    payload: EmergencyTriggerRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    group = await crud_emergency.get_group_by_code(db, payload.code)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Emergency code '{payload.code}' is not recognized in hospital protocols.",
        )

    alert = await crud_emergency.create_alert(
        db,
        group=group,
        ward=payload.ward,
        triggered_by=current_user,
        location_details=payload.location_details,
        notes=payload.notes,
    )

    assigned_user_ids = [str(m.id) for m in group.members]
    assigned_user_names = [m.full_name for m in group.members]

    # Real-Time Broadcast via Socket.IO
    alert_event = {
        "alert_id": str(alert.id),
        "code": alert.code,
        "code_name": alert.code_name,
        "color_hex": alert.color_hex,
        "ward": alert.ward,
        "location_details": alert.location_details,
        "notes": alert.notes,
        "triggered_by_id": str(current_user.id),
        "triggered_by_name": current_user.full_name,
        "triggered_at": alert.triggered_at.isoformat(),
        "call_to_action": group.call_to_action,
        "assigned_user_ids": assigned_user_ids,
        "assigned_user_names": assigned_user_names,
    }

    # 1. Broadcast to code group room
    await sio.emit("emergency:code_triggered", alert_event, room=f"emergency:code_{group.code}")

    # 2. Direct broadcast to each assigned responder's private room
    for uid in assigned_user_ids:
        await sio.emit("emergency:code_triggered", alert_event, room=f"user:{uid}")

    # 3. Broadcast to all active clinical staff room (Doctors, Nurses, Compounders)
    await sio.emit("emergency:code_triggered", alert_event, room="staff:emergency")

    return EmergencyAlertResponse(
        id=alert.id,
        code=alert.code,
        code_name=alert.code_name,
        color_hex=alert.color_hex,
        ward=alert.ward,
        location_details=alert.location_details,
        notes=alert.notes,
        status=alert.status,
        triggered_at=alert.triggered_at,
        triggered_by_id=alert.triggered_by_id,
        triggered_by_name=current_user.full_name,
        assigned_members_count=len(group.members),
        responders=[],
    )


@router.get(
    "/active",
    response_model=List[EmergencyAlertResponse],
    summary="List currently active emergency code alerts",
    dependencies=[Depends(require_permissions(["emergency:read"]))],
)
async def get_active_alerts(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    alerts = await crud_emergency.get_active_alerts(db)
    results = []
    for a in alerts:
        responders_list = [
            EmergencyResponderResponse(
                id=r.id,
                user_id=r.user_id,
                user_name=r.user.full_name if r.user else "Staff",
                status=r.status,
                responded_at=r.responded_at,
                note=r.note,
            )
            for r in a.responders
        ]
        results.append(
            EmergencyAlertResponse(
                id=a.id,
                code=a.code,
                code_name=a.code_name,
                color_hex=a.color_hex,
                ward=a.ward,
                location_details=a.location_details,
                notes=a.notes,
                status=a.status,
                triggered_at=a.triggered_at,
                triggered_by_id=a.triggered_by_id,
                triggered_by_name=a.triggered_by.full_name if a.triggered_by else "Staff",
                resolved_at=a.resolved_at,
                resolved_by_id=a.resolved_by_id,
                resolved_by_name=a.resolved_by.full_name if a.resolved_by else None,
                resolution_notes=a.resolution_notes,
                assigned_members_count=len(a.group.members) if a.group else 0,
                responders_count=len(responders_list),
                responders=responders_list,
            )
        )
    return results


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=EmergencyAlertResponse,
    summary="Staff responder acknowledges code and indicates they are en route",
    dependencies=[Depends(require_permissions(["emergency:read"]))],
)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: EmergencyAcknowledgeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    alert = await crud_emergency.get_alert_by_id(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency alert not found.")

    updated_alert = await crud_emergency.acknowledge_alert(
        db, alert=alert, user=current_user, note=payload.note
    )

    ack_event = {
        "alert_id": str(alert.id),
        "responder_id": str(current_user.id),
        "responder_name": current_user.full_name,
        "note": payload.note,
    }
    await sio.emit("emergency:alert_acknowledged", ack_event, room="staff:emergency")

    responders_list = [
        EmergencyResponderResponse(
            id=r.id,
            user_id=r.user_id,
            user_name=r.user.full_name if r.user else "Staff",
            status=r.status,
            responded_at=r.responded_at,
            note=r.note,
        )
        for r in updated_alert.responders
    ]

    return EmergencyAlertResponse(
        id=updated_alert.id,
        code=updated_alert.code,
        code_name=updated_alert.code_name,
        color_hex=updated_alert.color_hex,
        ward=updated_alert.ward,
        location_details=updated_alert.location_details,
        notes=updated_alert.notes,
        status=updated_alert.status,
        triggered_at=updated_alert.triggered_at,
        triggered_by_id=updated_alert.triggered_by_id,
        triggered_by_name=updated_alert.triggered_by.full_name if updated_alert.triggered_by else "Staff",
        assigned_members_count=len(updated_alert.group.members) if updated_alert.group else 0,
        responders_count=len(responders_list),
        responders=responders_list,
    )


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=EmergencyAlertResponse,
    summary="Mark emergency alert resolved",
    dependencies=[Depends(require_permissions(["emergency:trigger"]))],
)
async def resolve_alert(
    alert_id: uuid.UUID,
    payload: EmergencyResolveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    alert = await crud_emergency.get_alert_by_id(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency alert not found.")

    updated_alert = await crud_emergency.resolve_alert(
        db, alert=alert, user=current_user, resolution_notes=payload.resolution_notes
    )

    res_event = {
        "alert_id": str(alert.id),
        "code": alert.code,
        "ward": alert.ward,
        "resolved_by_id": str(current_user.id),
        "resolved_by_name": current_user.full_name,
        "resolution_notes": payload.resolution_notes,
    }
    await sio.emit("emergency:alert_resolved", res_event, room="staff:emergency")

    return EmergencyAlertResponse(
        id=updated_alert.id,
        code=updated_alert.code,
        code_name=updated_alert.code_name,
        color_hex=updated_alert.color_hex,
        ward=updated_alert.ward,
        location_details=updated_alert.location_details,
        notes=updated_alert.notes,
        status=updated_alert.status,
        triggered_at=updated_alert.triggered_at,
        triggered_by_id=updated_alert.triggered_by_id,
        triggered_by_name=updated_alert.triggered_by.full_name if updated_alert.triggered_by else "Staff",
        resolved_at=updated_alert.resolved_at,
        resolved_by_id=updated_alert.resolved_by_id,
        resolved_by_name=current_user.full_name,
        resolution_notes=updated_alert.resolution_notes,
        assigned_members_count=len(updated_alert.group.members) if updated_alert.group else 0,
        responders_count=len(updated_alert.responders),
        responders=[],
    )

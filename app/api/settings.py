from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.deps import AdminUser, CurrentUser, SessionDep
from app.models import AuditLog, BusinessHours
from app.schemas import BusinessHoursItem
from app.services.business_hours import DEFAULT_HOURS

router = APIRouter(prefix="/api/v1/settings", tags=["configurações"])


@router.get("/business-hours", response_model=list[BusinessHoursItem])
async def get_business_hours(_: CurrentUser, session: SessionDep) -> list[BusinessHoursItem]:
    rows = (await session.scalars(select(BusinessHours).order_by(BusinessHours.dia_semana))).all()
    if not rows:
        return [
            BusinessHoursItem(dia_semana=d, abre=a, fecha=f) for d, (a, f) in DEFAULT_HOURS.items()
        ]
    return [BusinessHoursItem(dia_semana=r.dia_semana, abre=r.abre, fecha=r.fecha) for r in rows]


@router.put("/business-hours", response_model=list[BusinessHoursItem])
async def put_business_hours(
    data: list[BusinessHoursItem], admin: AdminUser, session: SessionDep
) -> list[BusinessHoursItem]:
    if len({d.dia_semana for d in data}) != len(data):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Dia da semana repetido")
    if any(d.abre >= d.fecha for d in data):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Horário de abertura após o fechamento"
        )
    await session.execute(delete(BusinessHours))
    for d in data:
        session.add(BusinessHours(dia_semana=d.dia_semana, abre=d.abre, fecha=d.fecha))
    session.add(
        AuditLog(
            user_id=admin.id,
            acao="alterar",
            entidade="business_hours",
            diff={"dias": [d.model_dump(mode="json") for d in data]},
        )
    )
    await session.commit()
    return sorted(data, key=lambda d: d.dia_semana)

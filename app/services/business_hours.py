from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessHours, Holiday

# Padrão até o cliente confirmar: seg–sex 8h–18h, sáb 8h–12h.
DEFAULT_HOURS: dict[int, tuple[time, time]] = {
    0: (time(8), time(18)),
    1: (time(8), time(18)),
    2: (time(8), time(18)),
    3: (time(8), time(18)),
    4: (time(8), time(18)),
    5: (time(8), time(12)),
}

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


class Schedule:
    def __init__(self, hours: dict[int, tuple[time, time]], holidays: set[date]):
        self.hours = hours
        self.holidays = holidays

    def is_open(self, now: datetime) -> bool:
        if now.date() in self.holidays:
            return False
        window = self.hours.get(now.weekday())
        if window is None:
            return False
        abre, fecha = window
        return abre <= now.time() < fecha

    def describe(self) -> str:
        """Texto curto para a mensagem fora do horário."""
        partes = []
        for dia, (abre, fecha) in sorted(self.hours.items()):
            partes.append(f"{DIAS[dia]} das {abre:%H:%M} às {fecha:%H:%M}")
        return "; ".join(partes)


async def load_schedule(session: AsyncSession) -> Schedule:
    rows = (await session.scalars(select(BusinessHours))).all()
    hours = {r.dia_semana: (r.abre, r.fecha) for r in rows} or dict(DEFAULT_HOURS)
    holidays = set((await session.scalars(select(Holiday.data))).all())
    return Schedule(hours, holidays)

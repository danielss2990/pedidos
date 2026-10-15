import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api";
import { ErrorBox } from "../components/ui";
import { WEEKDAYS } from "../format";
import type { BusinessHours } from "../types";

interface DayRow {
  aberto: boolean;
  abre: string;
  fecha: string;
}

export function toRows(hours: BusinessHours[]): DayRow[] {
  return WEEKDAYS.map((_, dia) => {
    const h = hours.find((x) => x.dia_semana === dia);
    return h
      ? { aberto: true, abre: h.abre.slice(0, 5), fecha: h.fecha.slice(0, 5) }
      : { aberto: false, abre: "08:00", fecha: "18:00" };
  });
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const hours = useQuery({
    queryKey: ["business-hours"],
    queryFn: () => api<BusinessHours[]>("/api/v1/settings/business-hours"),
  });
  const [rows, setRows] = useState<DayRow[] | null>(null);
  useEffect(() => {
    if (hours.data) setRows(toRows(hours.data));
  }, [hours.data]);

  const save = useMutation({
    mutationFn: (data: DayRow[]) =>
      api<BusinessHours[]>("/api/v1/settings/business-hours", {
        method: "PUT",
        body: data
          .map((r, dia) => ({ dia_semana: dia, abre: r.abre, fecha: r.fecha, aberto: r.aberto }))
          .filter((r) => r.aberto)
          .map(({ dia_semana, abre, fecha }) => ({ dia_semana, abre, fecha })),
      }),
    onSuccess: (data) => queryClient.setQueryData(["business-hours"], data),
  });

  const update = (dia: number, patch: Partial<DayRow>) =>
    setRows((current) => current!.map((r, i) => (i === dia ? { ...r, ...patch } : r)));

  return (
    <div className="page narrow">
      <header className="page-header">
        <h1>Horário de atendimento</h1>
      </header>
      <p className="muted">
        Fora destes horários o bot responde uma vez com o horário e não processa pedidos.
      </p>
      <ErrorBox error={hours.error || save.error} />
      {rows && (
        <form
          className="hours"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(rows);
          }}
        >
          {rows.map((r, dia) => (
            <div key={dia} className={`hours-row ${r.aberto ? "" : "closed"}`}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={r.aberto}
                  onChange={(e) => update(dia, { aberto: e.target.checked })}
                />
                {WEEKDAYS[dia]}
              </label>
              {r.aberto ? (
                <>
                  <input
                    type="time"
                    value={r.abre}
                    onChange={(e) => update(dia, { abre: e.target.value })}
                    aria-label={`${WEEKDAYS[dia]}: abre`}
                  />
                  <span className="muted">às</span>
                  <input
                    type="time"
                    value={r.fecha}
                    onChange={(e) => update(dia, { fecha: e.target.value })}
                    aria-label={`${WEEKDAYS[dia]}: fecha`}
                  />
                </>
              ) : (
                <span className="muted">Fechado</span>
              )}
            </div>
          ))}
          <div className="form-actions">
            <button className="btn primary" type="submit" disabled={save.isPending}>
              Salvar horário
            </button>
            {save.isSuccess && <span className="good-text">Horário salvo.</span>}
          </div>
        </form>
      )}
    </div>
  );
}

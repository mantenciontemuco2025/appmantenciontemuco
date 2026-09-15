import type { LotoControl } from "./types";

export const LOTO_CONTROL_OPTIONS: {
  value: Exclude<LotoControl, "NOT_APPLICABLE">;
  label: string;
}[] = [
  { value: "LOTO_BLOQUEO", label: "LOTO / Bloqueo" },
  { value: "AST", label: "AST" },
  { value: "TARJETA_ROJA", label: "Tarjeta roja" },
  { value: "CHECKLIST_HERRAMIENTAS", label: "Checklist herramientas" },
];

export const LOTO_CONTROL_LABELS: Record<LotoControl, string> = {
  LOTO_BLOQUEO: "LOTO / Bloqueo",
  AST: "AST",
  TARJETA_ROJA: "Tarjeta roja",
  CHECKLIST_HERRAMIENTAS: "Checklist herramientas",
  NOT_APPLICABLE: "No aplica",
};

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Calendar dates from the API are date-only values (YYYY-MM-DD). Parsing them
// with new Date() treats them as UTC and can display the previous day in Chile.
export function formatDateOnly(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (match) return `${match[3]}-${match[2]}-${match[1]}`;
  return value;
}

export function todayDateInputValue(): string {
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// Format duration in minutes to "3 h 30 min"
export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h} h`;
  return `${h} h ${m} min`;
}

// Format duration in minutes as clear Spanish text for work-order details.
export function formatDurationLong(minutes: number): string {
  const total = Math.max(0, Math.round(minutes));
  const h = Math.floor(total / 60);
  const m = total % 60;
  const parts: string[] = [];
  if (h > 0) parts.push(`${h} ${h === 1 ? "hora" : "horas"}`);
  if (m > 0) parts.push(`${m} ${m === 1 ? "minuto" : "minutos"}`);
  return parts.length > 0 ? parts.join(" ") : "0 minutos";
}

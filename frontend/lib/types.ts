export type UserRole = "ADMIN" | "SUPERVISOR" | "WORKER";

export type MaintenanceType = "PREVENTIVE" | "CORRECTIVE" | "PREDICTIVE" | "PROYECTO" | "MONTAJE";
export type SyncStatus = "PENDING" | "SYNCED" | "FAILED";
export type LotoControl =
  | "LOTO_BLOQUEO"
  | "AST"
  | "TARJETA_ROJA"
  | "CHECKLIST_HERRAMIENTAS"
  | "NOT_APPLICABLE";

export interface User {
  id: number;
  full_name: string;
  email: string;
  role: UserRole;
  area_id: number | null;
  area_name: string | null;
  area_ids: number[];
  area_names: string[];
  is_active: boolean;
  signature: string | null;
}

export interface WorkerColumn {
  slot: number;
  column_key: string;
  column_letter: string;
  user_id: number | null;
  user_name: string | null;
}

export interface EquipmentNode {
  id: number;
  name: string;
}

// Catalog tree: Area -> Equipment (directly, no sections level)
export interface AreaNode {
  id: number;
  name: string;
  equipment: EquipmentNode[];
}

// GET /api/catalogs/tree returns a bare array of areas with nested equipment
export type CatalogTreeResponse = AreaNode[];

export interface KpiSummary {
  total_ots: number;
  completed_ots: number;
  pending_ots: number;
  in_progress_ots: number;
  cancelled_ots: number;
  planned_ots: number;
  executed_planned_ots: number;
  compliance_percent: number | null;
  compliance_target_percent: number;
  total_hours: number;
  total_person_hours: number;
  average_hours_per_ot: number;
  overdue_ots: number;
  stale_pending_ots: number;
}

export interface KpiMaintenanceRow {
  maintenance_type: string;
  total_ots: number;
  completed_ots: number;
  total_hours: number;
}

export interface KpiWorkerRow {
  user_id: number;
  worker_name: string;
  assigned_ots: number;
  completed_ots: number;
  total_hours: number;
  person_hours: number;
}

export interface KpiWorkerDetailRow {
  user_id: number;
  worker_name: string;
  area_name: string;
  maintenance_type: string;
  assigned_ots: number;
  completed_ots: number;
  person_hours: number;
}

export interface KpiAreaTypeRow {
  area_name: string;
  maintenance_type: string;
  total_ots: number;
  completed_ots: number;
  total_hours: number;
}

export interface KpiAreaRow {
  area_name: string;
  total_ots: number;
  completed_ots: number;
  total_hours: number;
  preventive_ots: number;
  corrective_ots: number;
}

export interface KpiSectionRow {
  area_name: string;
  section_name: string;
  total_ots: number;
  completed_ots: number;
  total_hours: number;
  preventive_ots: number;
  corrective_ots: number;
}

export interface KpiMonthRow {
  month: string;
  total_ots: number;
  completed_ots: number;
  planned_ots: number;
  executed_planned_ots: number;
  compliance_percent: number | null;
  total_hours: number;
}

export interface KpiResponse {
  generated_at: string;
  date_from: string;
  date_to: string;
  summary: KpiSummary;
  by_maintenance_type: KpiMaintenanceRow[];
  by_worker: KpiWorkerRow[];
  by_worker_detail: KpiWorkerDetailRow[];
  by_area: KpiAreaRow[];
  by_area_type: KpiAreaTypeRow[];
  by_section: KpiSectionRow[];
  by_month: KpiMonthRow[];
}

export interface Brief {
  id: number;
  name: string;
}

export interface MaintenanceRecord {
  id: number;
  date: string;
  area: Brief;
  section_name: string;       // free text, not a FK
  equipment: Brief;
  description: string;
  maintenance_type: MaintenanceType;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  created_by: { id: number; full_name: string };
  participants: { id: number; full_name: string }[];
  sheet_sync_status: SyncStatus;
  sheet_sync_error: string | null;
  sheet_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MaintenanceListItem {
  id: number;
  date: string;
  area: Brief;
  section_name: string;       // free text
  equipment: Brief;
  maintenance_type: MaintenanceType;
  duration_minutes: number;
  sheet_sync_status: SyncStatus;
  created_at: string;
}

export interface AuditLogEntry {
  id: number;
  user: { id: number; full_name: string };
  action: string;
  entity_type: string;
  entity_id: number | null;
  previous_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  created_at: string;
}

// Form draft: section is free text, not an ID selector
export interface MaintenanceDraft {
  date: string;
  area_id: number | null;
  section_name: string;        // free text typed by user
  equipment_id: number | null;
  description: string;
  maintenance_type: MaintenanceType;
  start_time: string;
  end_time: string;
  participant_ids: number[];
}

// ─────────────────────────────────────────────────────────────────────
// Work Order (OT)
// ─────────────────────────────────────────────────────────────────────

export type LotoStatus = "YES" | "NO" | "NOT_APPLICABLE";
export type WorkOrderStatus = "DRAFT" | "PENDING" | "IN_PROGRESS" | "COMPLETED" | "APPROVED" | "CANCELLED";
export type WorkTimeMode = "RANGE" | "MANUAL";

export interface WorkOrderRecord {
  id: number;
  ot_number: string;
  title: string;
  description: string | null;
  area_id: number;
  plant_area: string | null;
  area_name: string | null;
  equipment_id: number | null;
  equipment_name: string | null;
  section_name: string | null;
  maintenance_type: MaintenanceType;
  loto_status: LotoStatus;
  loto_controls: LotoControl[];
  folio: string | null;
  estimated_time: string | null;
  request_date: string | null;
  execution_date: string | null;
  resources_required: string | null;
  voucher_number: string | null;
  risks: string | null;
  observations: string | null;
  requested_by: string | null;
  approved_by: string | null;
  requested_signature: string | null;
  approved_signature: string | null;
  status: WorkOrderStatus;
  submitted_for_review: boolean;
  // ── Workflow fields ──
  responsible_user_id: number | null;
  responsible_user_name: string | null;
  participant_user_ids: number[];
  is_planned: boolean;
  scheduled_date: string | null;
  due_date: string | null;
  started_at: string | null;
  started_by_user_id: number | null;
  started_by_name: string | null;
  completed_at: string | null;
  completed_by_user_id: number | null;
  completed_by_name: string | null;
  work_time_mode: WorkTimeMode | null;
  work_start_time: string | null;
  work_end_time: string | null;
  worked_duration_minutes: number | null;
  actual_duration_minutes: number | null;
  completion_notes: string | null;
  approved_at: string | null;
  approved_by_user_id: number | null;
  approved_by_user_name: string | null;
  cancellation_reason: string | null;
  returned_at: string | null;
  returned_by_user_id: number | null;
  return_reason: string | null;
  // ── Google ──
  google_ot_file_id: string | null;
  google_ot_url: string | null;
  ot_sheet_sync_status: SyncStatus;
  ot_sheet_sync_error: string | null;
  ot_sheet_synced_at: string | null;
  monthly_sheet_sync_status: SyncStatus;
  monthly_sheet_sync_error: string | null;
  monthly_sheet_synced_at: string | null;
  created_by_user_id: number;
  created_by_name: string | null;
  participant_names: string[];
  created_at: string;
  updated_at: string;
}

// GET /api/work-orders/counter — admin counting panel
export interface WorkOrderCounter {
  current_year: number;
  total_all: number;
  per_year: Record<number, number>;
  per_month: Record<number, number>; // 0 = enero ... 11 = diciembre (año actual)
  next_ot_number: string;
}

export interface WorkOrderListItem {
  id: number;
  ot_number: string;
  title: string;
  area_name: string | null;
  plant_area?: string | null;
  equipment_name: string | null;
  section_name: string | null;
  maintenance_type: MaintenanceType;
  loto_status: LotoStatus;
  status: WorkOrderStatus;
  submitted_for_review: boolean;
  execution_date: string | null;
  request_date: string | null;
  ot_sheet_sync_status: SyncStatus;
  monthly_sheet_sync_status: SyncStatus;
  created_at: string;
  responsible_user_id: number | null;
  responsible_user_name: string | null;
  is_planned: boolean;
  scheduled_date: string | null;
  due_date: string | null;
}

export interface WorkOrderDraft {
  title: string;
  description: string;
  area_id: number | null;
  equipment_id: number | null;
  section_name: string;
  maintenance_type: MaintenanceType;
  loto_status: LotoStatus;
  folio: string;
  estimated_time: string;
  request_date: string;
  execution_date: string;
  resources_required: string;
  voucher_number: string;
  risks: string;
  observations: string;
  requested_by: string;
  approved_by: string;
  participant_names: string[];
}

// ─────────────────────────────────────────────────────────────────────
// Notifications
// ─────────────────────────────────────────────────────────────────────

export type NotificationType =
  | "OT_EMITIDA"
  | "OT_ASIGNADA"
  | "OT_COMPLETADA"
  | "OT_APROBADA"
  | "OT_DEVUELTA"
  | "OT_REASIGNADA";

export interface AppNotification {
  id: number;
  type: NotificationType;
  message: string;
  link: string | null;
  is_read: boolean;
  created_at: string;
}

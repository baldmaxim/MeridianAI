// --- Справочники (Этап 1 MVP) ---

export interface Customer {
  id: number;
  owner_user_id: number;
  name: string;
  inn: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectObject {
  id: number;
  owner_user_id: number;
  customer_id: number;
  name: string;
  address: string | null;
  description: string | null;
  notes: string | null;
  payhub_project_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  customer_name: string | null;
}

export interface MeetingParticipant {
  id: number;
  meeting_id: number;
  user_id: number;
  role: 'owner' | 'participant' | 'viewer';
  created_at: string;
  email: string | null;
  display_name: string | null;
}

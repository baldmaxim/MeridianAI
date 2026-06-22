import type { RoomParticipant } from '../types';

// Уникальный участник-человек: агрегирует все его устройства/соединения в комнате.
export interface ParticipantUser {
  userId: number | null;
  label: string;
  deviceCount: number;
  roles: string[];          // device_role каждого соединения
  deviceLabels: string[];   // ярлыки устройств (UA), уникальные (напр. «iPhone · Safari»)
  isRecording: boolean;     // ведёт ли звук с какого-либо устройства
  isHelper: boolean;        // помогает ли распознаванию (shadow) с какого-либо устройства
}

const ROLE_LABELS: Record<string, string> = {
  desktop: 'компьютер',
  phone: 'телефон',
  secondary: 'второй канал',
  observer: 'наблюдатель',
  viewer: 'просмотр',
  participant: 'участник',
};

export function deviceRoleLabel(role: string): string {
  return ROLE_LABELS[role] || role;
}

// Свернуть соединения в список уникальных пользователей (дедуп по user_id).
// Соединения без user_id (теоретически) считаются отдельными «гостями».
export function uniqueParticipantUsers(participants: RoomParticipant[]): ParticipantUser[] {
  const byUser = new Map<string, ParticipantUser>();
  for (const p of participants) {
    const key = p.user_id != null ? `u:${p.user_id}` : `c:${p.connection_id}`;
    const deviceLabel = p.device_label || deviceRoleLabel(p.device_role);
    const existing = byUser.get(key);
    if (existing) {
      existing.deviceCount += 1;
      existing.roles.push(p.device_role);
      if (!existing.deviceLabels.includes(deviceLabel)) existing.deviceLabels.push(deviceLabel);
      existing.isRecording = existing.isRecording || p.is_active_audio_source;
      existing.isHelper = existing.isHelper || p.is_helper;
      if (existing.label === 'Гость' && p.user_label) existing.label = p.user_label;
    } else {
      byUser.set(key, {
        userId: p.user_id,
        label: p.user_label || 'Гость',
        deviceCount: 1,
        roles: [p.device_role],
        deviceLabels: [deviceLabel],
        isRecording: p.is_active_audio_source,
        isHelper: p.is_helper,
      });
    }
  }
  return Array.from(byUser.values());
}

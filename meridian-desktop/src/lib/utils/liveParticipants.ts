import type { LiveParticipant } from "@/bindings";

/** What kind of device a connection is, for its caption. */
export type DeviceKind = "app" | "phone" | "browser" | "other";

export interface ParticipantDevice {
  connectionId: string;
  kind: DeviceKind;
  /** The server's own label (or the role), for the `other` kind. */
  fallback: string;
  isSelf: boolean;
  isRecording: boolean;
}

export interface ParticipantPerson {
  key: string;
  /** `null`: the server did not name the person. */
  name: string | null;
  devices: ParticipantDevice[];
}

// The server labels the app's connection "Приложение · <device name>"; a
// browser's one is made from its User-Agent ("Windows · Chrome"), and both
// of them join as the `desktop` role.
const APP_LABEL = /^(приложение|application|app)\b/i;
const PHONE_LABEL = /iphone|ipad|android/i;
const BROWSER_ROLES = new Set(["desktop", "viewer", "participant"]);

export const deviceKindOf = (p: LiveParticipant): DeviceKind => {
  const label = p.device_label ?? "";
  if (APP_LABEL.test(label)) return "app";
  if (p.device_role === "phone" || PHONE_LABEL.test(label)) return "phone";
  if (BROWSER_ROLES.has(p.device_role) || label) return "browser";
  return "other";
};

/** Connections folded into people: by `user_id`, without it by connection. */
export const groupParticipants = (
  participants: LiveParticipant[],
): ParticipantPerson[] => {
  const byKey = new Map<string, ParticipantPerson>();
  for (const p of participants) {
    const key = p.user_id !== null ? `u:${p.user_id}` : `c:${p.connection_id}`;
    const device: ParticipantDevice = {
      connectionId: p.connection_id,
      kind: deviceKindOf(p),
      fallback: p.device_label || p.device_role,
      isSelf: p.is_self,
      isRecording: p.is_active_audio_source,
    };
    const person = byKey.get(key);
    if (person) {
      person.devices.push(device);
      person.name ??= p.user_label;
    } else {
      byKey.set(key, { key, name: p.user_label, devices: [device] });
    }
  }
  return Array.from(byKey.values());
};

import { useState, useEffect } from 'react';
import { getRoles, createRole, updateRole, deleteRole } from '../../api/roles';
import { theme } from '../../styles/theme';
import type { NegotiationRole } from '../../types';

interface Props {
  onRoleSelect: (roleId: number) => void;
}

const EMPTY_FORM = {
  name: '',
  description: '',
  interests: '',
  opponents: '',
  custom_instructions: '',
};

export function RolesTab({ onRoleSelect }: Props) {
  const [roles, setRoles] = useState<NegotiationRole[]>([]);
  const [activeRoleId, setActiveRoleId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showPrompts, setShowPrompts] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getRoles().then((r) => {
      setRoles(r);
      if (r.length > 0 && !activeRoleId) {
        setActiveRoleId(r[0].id);
      }
    });
  }, []);

  const selectRole = (id: number) => {
    setActiveRoleId(id);
    onRoleSelect(id);
  };

  const startEdit = (role: NegotiationRole) => {
    setEditingId(role.id);
    setCreating(false);
    setForm({
      name: role.name,
      description: role.description,
      interests: role.interests,
      opponents: role.opponents,
      custom_instructions: role.custom_instructions,
    });
  };

  const startCreate = () => {
    setCreating(true);
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const cancel = () => {
    setCreating(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      if (creating) {
        const newRole = await createRole(form);
        setRoles((prev) => [...prev, newRole]);
        selectRole(newRole.id);
      } else if (editingId) {
        const updated = await updateRole(editingId, form);
        setRoles((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
        if (activeRoleId === editingId) {
          onRoleSelect(editingId);
        }
      }
      cancel();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    await deleteRole(id);
    setRoles((prev) => prev.filter((r) => r.id !== id));
    if (activeRoleId === id && roles.length > 1) {
      const next = roles.find((r) => r.id !== id);
      if (next) selectRole(next.id);
    }
  };

  const activeRole = roles.find((r) => r.id === activeRoleId);

  const buildPreviewPrompt = (r: typeof form) => {
    if (!r.name) return '';
    return `Ты эксперт по переговорам в строительной отрасли.
Ты помогаешь роли "${r.name}" (${r.description || '...'}) вести переговоры с ${r.opponents || '...'}.
ВАЖНО: Ты ВСЕГДА на стороне "${r.name}", защищаешь ЕГО интересы.
Интересы: ${r.interests || '...'}

Дополнительные правила:
${r.custom_instructions || '(не указаны)'}`;
  };

  const isEditing = creating || editingId !== null;

  return (
    <div style={s.container}>
      {/* Role list */}
      <div style={s.roleList}>
        <div style={s.listHeader}>
          <span style={s.dot} />
          <span style={s.headerTitle}>Роли переговоров</span>
        </div>

        {roles.map((role) => (
          <div
            key={role.id}
            onClick={() => selectRole(role.id)}
            style={{
              ...s.roleCard,
              borderColor: activeRoleId === role.id ? theme.accent.amber : theme.border.default,
              background: activeRoleId === role.id ? theme.accent.amberGlow : theme.bg.elevated,
            }}
          >
            <div style={s.roleCardTop}>
              <span style={s.roleName}>{role.name}</span>
              {role.is_default && <span style={s.badge}>По умолч.</span>}
            </div>
            <div style={s.roleDesc}>{role.description}</div>
            <div style={s.roleActions}>
              <button style={s.linkBtn} onClick={(e) => { e.stopPropagation(); startEdit(role); }}>
                Редактировать
              </button>
              {!role.is_default && (
                <button
                  style={{ ...s.linkBtn, color: theme.accent.red }}
                  onClick={(e) => { e.stopPropagation(); handleDelete(role.id); }}
                >
                  Удалить
                </button>
              )}
            </div>
          </div>
        ))}

        <button style={s.addBtn} onClick={startCreate}>+ Новая роль</button>
      </div>

      {/* Edit / Create form or preview */}
      <div style={s.detail}>
        {isEditing ? (
          <div style={s.formCard}>
            <div style={s.listHeader}>
              <span style={s.dot} />
              <span style={s.headerTitle}>{creating ? 'Новая роль' : 'Редактирование'}</span>
            </div>

            <label style={s.label}>Название роли</label>
            <input
              style={s.input}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Например: Генподрядчик, Заказчик, Инвестор..."
            />

            <label style={s.label}>Описание — кто вы</label>
            <textarea
              style={s.textarea}
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Генеральный подрядчик в строительной отрасли"
            />

            <label style={s.label}>Чьи интересы защищать</label>
            <textarea
              style={s.textarea}
              rows={2}
              value={form.interests}
              onChange={(e) => setForm({ ...form, interests: e.target.value })}
              placeholder="Максимизация прибыли, защита от рисков, контроль сроков"
            />

            <label style={s.label}>Против кого переговоры</label>
            <input
              style={s.input}
              value={form.opponents}
              onChange={(e) => setForm({ ...form, opponents: e.target.value })}
              placeholder="Заказчики и субподрядчики"
            />

            <label style={s.label}>Дополнительные инструкции для ИИ</label>
            <textarea
              style={s.textarea}
              rows={3}
              value={form.custom_instructions}
              onChange={(e) => setForm({ ...form, custom_instructions: e.target.value })}
              placeholder="Не выдумывай номера договоров. Давай только общие рекомендации..."
            />

            {/* Prompt preview */}
            <button
              style={s.toggleBtn}
              onClick={() => setShowPrompts(!showPrompts)}
            >
              {showPrompts ? 'Скрыть промт' : 'Показать собранный промт'}
            </button>
            {showPrompts && (
              <pre style={s.promptPreview}>{buildPreviewPrompt(form)}</pre>
            )}

            <div style={s.formActions}>
              <button style={s.saveBtn} onClick={handleSave} disabled={saving || !form.name.trim()}>
                {saving ? 'Сохранение...' : 'Сохранить'}
              </button>
              <button style={s.cancelBtn} onClick={cancel}>Отмена</button>
            </div>
          </div>
        ) : activeRole ? (
          <div style={s.formCard}>
            <div style={s.listHeader}>
              <span style={s.dot} />
              <span style={s.headerTitle}>Активная роль: {activeRole.name}</span>
            </div>

            <div style={s.previewRow}>
              <span style={s.previewLabel}>Описание</span>
              <span style={s.previewValue}>{activeRole.description || '—'}</span>
            </div>
            <div style={s.previewRow}>
              <span style={s.previewLabel}>Интересы</span>
              <span style={s.previewValue}>{activeRole.interests || '—'}</span>
            </div>
            <div style={s.previewRow}>
              <span style={s.previewLabel}>Оппоненты</span>
              <span style={s.previewValue}>{activeRole.opponents || '—'}</span>
            </div>
            <div style={s.previewRow}>
              <span style={s.previewLabel}>Инструкции ИИ</span>
              <span style={s.previewValue}>{activeRole.custom_instructions || '—'}</span>
            </div>

            <button
              style={s.toggleBtn}
              onClick={() => setShowPrompts(!showPrompts)}
            >
              {showPrompts ? 'Скрыть промт' : 'Показать собранный промт'}
            </button>
            {showPrompts && (
              <pre style={s.promptPreview}>{buildPreviewPrompt(activeRole)}</pre>
            )}
          </div>
        ) : (
          <div style={s.formCard}>
            <div style={{ color: theme.text.muted, fontSize: 13 }}>
              Выберите роль или создайте новую
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  container: {
    display: 'grid',
    gridTemplateColumns: '280px 1fr',
    gap: 20,
  },
  roleList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  listHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
  headerTitle: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
  },
  roleCard: {
    padding: '12px 14px',
    borderRadius: 8,
    border: `1px solid ${theme.border.default}`,
    cursor: 'pointer',
    transition: 'border-color 0.2s',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  roleCardTop: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  roleName: {
    fontFamily: theme.font.body,
    fontWeight: 600,
    fontSize: 13,
    color: theme.text.primary,
  },
  badge: {
    fontSize: 9,
    fontFamily: theme.font.mono,
    color: theme.accent.amber,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 4,
    padding: '1px 5px',
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
  },
  roleDesc: {
    fontSize: 11,
    color: theme.text.secondary,
    fontFamily: theme.font.body,
  },
  roleActions: {
    display: 'flex',
    gap: 12,
    marginTop: 4,
  },
  linkBtn: {
    background: 'none',
    border: 'none',
    color: theme.accent.amber,
    fontSize: 10,
    fontFamily: theme.font.mono,
    cursor: 'pointer',
    padding: 0,
    letterSpacing: '0.04em',
  },
  addBtn: {
    padding: '10px 14px',
    background: 'transparent',
    border: `1px dashed ${theme.border.default}`,
    borderRadius: 8,
    color: theme.text.secondary,
    fontSize: 12,
    fontFamily: theme.font.body,
    cursor: 'pointer',
    textAlign: 'left' as const,
    transition: 'border-color 0.2s, color 0.2s',
  },
  detail: {
    display: 'flex',
    flexDirection: 'column',
  },
  formCard: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  label: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.amber,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    marginTop: 8,
  },
  input: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.body,
    outline: 'none',
  },
  textarea: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.body,
    outline: 'none',
    resize: 'vertical' as const,
  },
  toggleBtn: {
    background: 'none',
    border: 'none',
    color: theme.text.secondary,
    fontSize: 11,
    fontFamily: theme.font.mono,
    cursor: 'pointer',
    padding: '6px 0',
    textAlign: 'left' as const,
    letterSpacing: '0.04em',
    marginTop: 8,
  },
  promptPreview: {
    background: theme.bg.primary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    padding: 14,
    color: theme.text.secondary,
    fontSize: 11,
    fontFamily: theme.font.mono,
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap' as const,
    overflowX: 'auto' as const,
    maxHeight: 300,
    overflowY: 'auto' as const,
  },
  formActions: {
    display: 'flex',
    gap: 10,
    marginTop: 12,
  },
  saveBtn: {
    padding: '9px 22px',
    background: theme.accent.amber,
    border: 'none',
    borderRadius: 7,
    color: '#080A0F',
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 600,
    fontFamily: theme.font.body,
  },
  cancelBtn: {
    padding: '9px 22px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: theme.font.body,
  },
  previewRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: '6px 0',
    borderBottom: `1px solid ${theme.border.default}`,
  },
  previewLabel: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.amber,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
  },
  previewValue: {
    fontSize: 13,
    fontFamily: theme.font.body,
    color: theme.text.primary,
    lineHeight: 1.5,
  },
};

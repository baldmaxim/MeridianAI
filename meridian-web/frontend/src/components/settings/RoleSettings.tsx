import { useState, useEffect } from 'react';
import { getRoles, createRole, updateRole, deleteRole } from '../../api/roles';
import { theme } from '../../styles/theme';
import { Select, TextInput } from '../common';
import type { NegotiationRole } from '../../types';
import styles from './RoleSettings.module.css';
import { cx } from '../../utils/cx';

const EMPTY_FORM = {
  name: '',
  description: '',
  interests: '',
  opponents: '',
  custom_instructions: '',
};

const PRESET_INSTRUCTIONS = [
  'Не выдумывай номера договоров, пунктов, статей или документов',
  'Давай только общие рекомендации на основе контекста разговора',
  'Ссылайся на загруженные документы, если они релевантны',
  'Отвечай кратко и по существу, без воды',
  'Предупреждай о возможных рисках и подводных камнях',
  'Предлагай конкретные формулировки для ответов оппоненту',
  'Учитывай рыночные цены и нормы строительной отрасли',
  'Не соглашайся на первое предложение оппонента',
  'Фокусируйся на защите финансовых интересов',
  'Предлагай альтернативные варианты при тупике в переговорах',
];

export function RoleSettings() {
  const [roles, setRoles] = useState<NegotiationRole[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showPrompts, setShowPrompts] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getRoles().then(setRoles);
  }, []);

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
      } else if (editingId) {
        const updated = await updateRole(editingId, form);
        setRoles((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      }
      cancel();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    await deleteRole(id);
    setRoles((prev) => prev.filter((r) => r.id !== id));
    if (editingId === id) cancel();
  };

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
    <div className={cx('roles-container', styles.container)}>
      {/* Role list */}
      <div className={styles.roleList}>
        <div className={styles.listHeader}>
          <span className={styles.dot} />
          <span className={styles.headerTitle}>Роли переговоров</span>
        </div>

        {roles.map((role) => (
          <div
            key={role.id}
            onClick={() => startEdit(role)}
            className={cx(styles.roleCard, editingId === role.id && styles.roleCardActive)}
          >
            <div className={styles.roleCardTop}>
              <span className={styles.roleName}>{role.name}</span>
              {role.is_default && <span className={styles.badge}>По умолч.</span>}
            </div>
            <div className={styles.roleDesc}>{role.description}</div>
            <div className={styles.roleActions}>
              <button className={styles.linkBtn} onClick={(e) => { e.stopPropagation(); startEdit(role); }}>
                Редактировать
              </button>
              {!role.is_default && (
                <button
                  className={cx(styles.linkBtn, styles.dangerLinkBtn)}
                  onClick={(e) => { e.stopPropagation(); handleDelete(role.id); }}
                >
                  Удалить
                </button>
              )}
            </div>
          </div>
        ))}

        <button className={styles.addBtn} onClick={startCreate}>+ Новая роль</button>
      </div>

      {/* Edit / Create form */}
      <div className={styles.detail}>
        {isEditing ? (
          <div className={styles.formCard}>
            <div className={styles.listHeader}>
              <span className={styles.dot} />
              <span className={styles.headerTitle}>{creating ? 'Новая роль' : 'Редактирование'}</span>
            </div>

            <label className={styles.label}>Название роли</label>
            <TextInput
              inputClassName={styles.input}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              onClear={() => setForm({ ...form, name: '' })}
              clearLabel="название роли"
              placeholder="Например: Генподрядчик, Заказчик, Инвестор..."
            />

            <label className={styles.label}>Описание — кто вы</label>
            <textarea
              className={styles.textarea}
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Генеральный подрядчик в строительной отрасли"
            />

            <label className={styles.label}>Чьи интересы защищать</label>
            <textarea
              className={styles.textarea}
              rows={2}
              value={form.interests}
              onChange={(e) => setForm({ ...form, interests: e.target.value })}
              placeholder="Максимизация прибыли, защита от рисков, контроль сроков"
            />

            <label className={styles.label}>Против кого переговоры</label>
            <TextInput
              inputClassName={styles.input}
              value={form.opponents}
              onChange={(e) => setForm({ ...form, opponents: e.target.value })}
              onClear={() => setForm({ ...form, opponents: '' })}
              clearLabel="оппонентов"
              placeholder="Заказчики и субподрядчики"
            />

            <label className={styles.label}>Дополнительные инструкции для ИИ</label>
            <Select
              style={selectStyle}
              value=""
              placeholder="Выбрать из шаблонов..."
              ariaLabel="Шаблоны инструкций"
              onChange={(v) => {
                if (!v) return;
                const cur = form.custom_instructions.trim();
                const next = cur ? `${cur}\n${v}` : v;
                setForm({ ...form, custom_instructions: next });
              }}
              options={PRESET_INSTRUCTIONS.map((text) => ({ value: text, label: text }))}
            />
            <textarea
              className={styles.textarea}
              rows={3}
              value={form.custom_instructions}
              onChange={(e) => setForm({ ...form, custom_instructions: e.target.value })}
              placeholder="Не выдумывай номера договоров. Давай только общие рекомендации..."
            />

            {/* Prompt preview */}
            <button
              className={styles.toggleBtn}
              onClick={() => setShowPrompts(!showPrompts)}
            >
              {showPrompts ? 'Скрыть промт' : 'Показать собранный промт'}
            </button>
            {showPrompts && (
              <pre className={styles.promptPreview}>{buildPreviewPrompt(form)}</pre>
            )}

            <div className={styles.formActions}>
              <button className={styles.saveBtn} onClick={handleSave} disabled={saving || !form.name.trim()}>
                {saving ? 'Сохранение...' : 'Сохранить'}
              </button>
              <button className={styles.cancelBtn} onClick={cancel}>Отмена</button>
            </div>
          </div>
        ) : (
          <div className={styles.formCard}>
            <div className={styles.hintText}>
              Выберите роль для редактирования или создайте новую
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Стиль триггера <Select>: компонент принимает только style (не className). */
const selectStyle: React.CSSProperties = {
  padding: '10px 14px',
  background: theme.bg.input,
  border: `1px solid ${theme.border.default}`,
  borderRadius: 7,
  color: theme.text.secondary,
  fontSize: 13,
  fontFamily: theme.font.body,
  outline: 'none',
  cursor: 'pointer',
  appearance: 'auto',
};

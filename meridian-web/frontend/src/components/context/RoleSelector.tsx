import { useState, useEffect } from 'react';
import { getRoles } from '../../api/roles';
import { useMeetingStore } from '../../store/meetingStore';
import { Select } from '../common';
import type { NegotiationRole } from '../../types';
import s from './RoleSelector.module.css';

interface Props {
  onRoleSelect: (roleId: number) => void;
}

export function RoleSelector({ onRoleSelect }: Props) {
  const setActiveRoleName = useMeetingStore((s) => s.setActiveRoleName);
  const [roles, setRoles] = useState<NegotiationRole[]>([]);
  const [activeRoleId, setActiveRoleId] = useState<number | null>(null);

  useEffect(() => {
    getRoles().then((r) => {
      setRoles(r);
      if (r.length > 0) {
        // Бэкенд уже грузит default-роль при инициализации комнаты — здесь только
        // отражаем её в UI, без отправки change_role.
        setActiveRoleId(r[0].id);
        setActiveRoleName(r[0].name);
      }
    });
  }, [setActiveRoleName]);

  const handleChange = (v: string) => {
    const id = Number(v);
    if (!id) return;
    setActiveRoleId(id);
    onRoleSelect(id);
    const role = roles.find((r) => r.id === id);
    if (role) setActiveRoleName(role.name);
  };

  return (
    <div className={s.wrap}>
      <Select
        triggerClassName={s.select}
        value={activeRoleId != null ? String(activeRoleId) : ''}
        placeholder="Выберите роль..."
        ariaLabel="Активная роль для подсказок"
        onChange={handleChange}
        options={roles.map((r) => ({ value: String(r.id), label: r.name }))}
      />
      <span className={s.hint}>Создать или изменить роли можно в «Настройки → Роли переговоров»</span>
    </div>
  );
}

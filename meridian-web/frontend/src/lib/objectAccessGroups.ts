import type { Customer, ProjectObject } from '../types';
import type { IObjectAccess } from '../api/objectAccess';

export interface IAccessGroup {
  customerId: number;
  customerName: string;
  objects: ProjectObject[];
}

const norm = (s: string): string => s.trim().toLowerCase();

/**
 * Группировка проектов по заказчику с фильтром поиска (по имени проекта и заказчика).
 * Совпало имя заказчика — показываются все его проекты; заказчики без проектов тоже
 * остаются в списке (им можно выдать доступ «на будущее»).
 */
export const groupObjectsByCustomer = (
  objects: ProjectObject[],
  customers: Customer[],
  query: string,
): IAccessGroup[] => {
  const q = norm(query);
  const map = new Map<number, IAccessGroup>();
  for (const c of customers) map.set(c.id, { customerId: c.id, customerName: c.name, objects: [] });
  for (const o of objects) {
    let g = map.get(o.customer_id);
    if (!g) {
      g = { customerId: o.customer_id, customerName: o.customer_name ?? 'Без заказчика', objects: [] };
      map.set(o.customer_id, g);
    }
    g.objects.push(o);
  }
  const groups = [...map.values()].sort((a, b) => a.customerName.localeCompare(b.customerName, 'ru'));
  if (!q) return groups;
  const result: IAccessGroup[] = [];
  for (const g of groups) {
    if (norm(g.customerName).includes(q)) { result.push(g); continue; }
    const matched = g.objects.filter((o) => norm(o.name).includes(q));
    if (matched.length > 0) result.push({ ...g, objects: matched });
  }
  return result;
};

const toggleId = (ids: number[], id: number): number[] =>
  ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];

export const toggleCustomerAccess = (access: IObjectAccess, customerId: number): IObjectAccess => ({
  ...access,
  customer_ids: toggleId(access.customer_ids, customerId),
});

export const toggleObjectAccess = (access: IObjectAccess, objectId: number): IObjectAccess => ({
  ...access,
  object_ids: toggleId(access.object_ids, objectId),
});

/** Проект отмечен: напрямую или через заказчика (тогда он ещё и заблокирован). */
export const isObjectChecked = (access: IObjectAccess, o: ProjectObject): boolean =>
  access.customer_ids.includes(o.customer_id) || access.object_ids.includes(o.id);

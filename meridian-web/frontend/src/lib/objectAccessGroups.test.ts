import { describe, expect, it } from 'vitest';
import type { Customer, ProjectObject } from '../types';
import type { IObjectAccess } from '../api/objectAccess';
import {
  groupObjectsByCustomer, isObjectChecked, toggleCustomerAccess, toggleObjectAccess,
} from './objectAccessGroups';

const customer = (id: number, name: string): Customer => ({
  id, owner_user_id: 1, name, inn: null, notes: null, created_at: '', updated_at: '',
});
const object = (id: number, customer_id: number, name: string, customer_name: string): ProjectObject => ({
  id, owner_user_id: 1, customer_id, name, address: null, description: null, notes: null,
  payhub_project_id: null, is_active: true, tender_won: false, created_at: '', updated_at: '', customer_name,
});

const customers = [customer(1, 'Стройзаказ'), customer(2, 'Альфа'), customer(3, 'Пустой')];
const objects = [
  object(10, 1, 'ЖК Рассвет', 'Стройзаказ'),
  object(11, 1, 'Склад', 'Стройзаказ'),
  object(20, 2, 'Мост', 'Альфа'),
];
const empty: IObjectAccess = { all_objects: false, customer_ids: [], object_ids: [] };

describe('groupObjectsByCustomer', () => {
  it('группирует по заказчику, сортирует и оставляет заказчиков без проектов', () => {
    const g = groupObjectsByCustomer(objects, customers, '');
    expect(g.map((x) => x.customerName)).toEqual(['Альфа', 'Пустой', 'Стройзаказ']);
    expect(g[2].objects).toHaveLength(2);
  });

  it('поиск по имени проекта оставляет только совпавшие проекты', () => {
    const g = groupObjectsByCustomer(objects, customers, 'рассвет');
    expect(g).toHaveLength(1);
    expect(g[0].objects.map((o) => o.id)).toEqual([10]);
  });

  it('поиск по заказчику показывает все его проекты', () => {
    const g = groupObjectsByCustomer(objects, customers, 'строй');
    expect(g).toHaveLength(1);
    expect(g[0].objects).toHaveLength(2);
  });
});

describe('отметка доступа', () => {
  it('отмеченный заказчик отмечает все его проекты', () => {
    const access = toggleCustomerAccess(empty, 1);
    expect(isObjectChecked(access, objects[0])).toBe(true);
    expect(isObjectChecked(access, objects[1])).toBe(true);
    expect(isObjectChecked(access, objects[2])).toBe(false);
  });

  it('повторный клик снимает отметку', () => {
    expect(toggleCustomerAccess(toggleCustomerAccess(empty, 1), 1).customer_ids).toEqual([]);
    expect(toggleObjectAccess(toggleObjectAccess(empty, 20), 20).object_ids).toEqual([]);
  });
});

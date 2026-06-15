import api from './client';
import type { Customer } from '../types';

export interface CustomerInput {
  name: string;
  inn?: string | null;
  notes?: string | null;
}

export async function listCustomers(): Promise<Customer[]> {
  const { data } = await api.get<Customer[]>('/customers');
  return data;
}

export async function getCustomer(id: number): Promise<Customer> {
  const { data } = await api.get<Customer>(`/customers/${id}`);
  return data;
}

export async function createCustomer(input: CustomerInput): Promise<Customer> {
  const { data } = await api.post<Customer>('/customers', input);
  return data;
}

export async function updateCustomer(id: number, input: Partial<CustomerInput>): Promise<Customer> {
  const { data } = await api.put<Customer>(`/customers/${id}`, input);
  return data;
}

export async function deleteCustomer(id: number): Promise<void> {
  await api.delete(`/customers/${id}`);
}

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listCustomers, createCustomer, updateCustomer, deleteCustomer, type CustomerInput,
} from '../../api/customers';
import {
  listObjects, createObject, updateObject, deleteObject, type ProjectObjectInput,
} from '../../api/objects';

export const directoryKeys = {
  customers: ['customers'] as const,
  objects: (customerId?: number) => ['objects', customerId ?? null] as const,
  objectsAll: ['objects'] as const,
};

// --- заказчики ---

export function useCustomers() {
  return useQuery({ queryKey: directoryKeys.customers, queryFn: listCustomers });
}

export function useCreateCustomer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CustomerInput) => createCustomer(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: directoryKeys.customers }),
  });
}

export function useUpdateCustomer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: Partial<CustomerInput> }) => updateCustomer(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: directoryKeys.customers }),
  });
}

export function useDeleteCustomer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteCustomer(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: directoryKeys.customers }),
  });
}

// --- объекты ---

export function useObjects(customerId?: number) {
  return useQuery({
    queryKey: directoryKeys.objects(customerId),
    queryFn: () => listObjects(customerId),
  });
}

export function useCreateObject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ProjectObjectInput) => createObject(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: directoryKeys.objectsAll }),
  });
}

export function useUpdateObject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: Partial<ProjectObjectInput> }) => updateObject(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: directoryKeys.objectsAll }),
  });
}

export function useDeleteObject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteObject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: directoryKeys.objectsAll }),
  });
}

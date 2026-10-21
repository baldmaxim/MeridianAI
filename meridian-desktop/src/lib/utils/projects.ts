import type { ProjectCustomer } from "@/bindings";

export interface ProjectChoice {
  customerId: number | null;
  objectId: number | null;
  customerName: string | null;
  objectName: string | null;
}

export const NO_PROJECT_CHOICE: ProjectChoice = {
  customerId: null,
  objectId: null,
  customerName: null,
  objectName: null,
};

/** Ids with their names from the reference book; unknown ids are dropped. */
export const resolveProject = (
  customers: ProjectCustomer[],
  customerId: number | null,
  objectId: number | null,
): ProjectChoice => {
  const customer = customers.find((c) => c.id === customerId);
  if (!customer) return NO_PROJECT_CHOICE;
  const object = customer.objects.find((o) => o.id === objectId);
  return {
    customerId: customer.id,
    objectId: object?.id ?? null,
    customerName: customer.name,
    objectName: object?.name ?? null,
  };
};

/**
 * The reference book plus the meeting's current project, so a project that is
 * missing from the cache is still shown in the selects.
 */
export const withCurrentProject = (
  customers: ProjectCustomer[],
  current: ProjectChoice,
): ProjectCustomer[] => {
  if (current.customerId === null) return customers;
  const existing = customers.find((c) => c.id === current.customerId);
  const object =
    current.objectId !== null
      ? {
          id: current.objectId,
          name: current.objectName ?? String(current.objectId),
          address: null,
        }
      : null;
  if (!existing) {
    return [
      ...customers,
      {
        id: current.customerId,
        name: current.customerName ?? String(current.customerId),
        objects: object ? [object] : [],
      },
    ];
  }
  if (!object || existing.objects.some((o) => o.id === object.id)) {
    return customers;
  }
  return customers.map((c) =>
    c.id === existing.id ? { ...c, objects: [...c.objects, object] } : c,
  );
};

import { useEffect, useState } from 'react';
import { listObjectOfferSubmissions } from '../api/objects';
import type { IOfferSubmission } from '../types';

const EMPTY: IOfferSubmission[] = [];

/** Подачи КП объекта (от новой к старой). Без объекта или при ошибке — пустой список. */
export const useOfferSubmissions = (objectId: number | null | undefined): IOfferSubmission[] => {
  const [state, setState] = useState<{ objectId: number; list: IOfferSubmission[] } | null>(null);

  useEffect(() => {
    if (objectId == null) return;
    let cancelled = false;
    listObjectOfferSubmissions(objectId)
      .then((list) => { if (!cancelled) setState({ objectId, list }); })
      .catch(() => { if (!cancelled) setState({ objectId, list: EMPTY }); });
    return () => { cancelled = true; };
  }, [objectId]);

  // Список другого объекта (пока грузится новый) не показываем.
  return state != null && state.objectId === objectId ? state.list : EMPTY;
};

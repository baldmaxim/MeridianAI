import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type {
  GlossaryTerm, TriggerPhrase, NegotiationPlaybook, CounterpartyTrait, ForbiddenPhrase, KnowledgeKind,
} from '../../types';
import {
  listTerms, listTriggers, listPlaybooks, listTraits, listForbidden, archiveItem,
  type KnowledgeFilters,
} from '../../api/knowledge';

export const knowledgeKeys = {
  all: ['knowledge'] as const,
  list: (kind: KnowledgeKind, filters: KnowledgeFilters) => ['knowledge', kind, filters] as const,
};

type KnowledgeItem =
  | GlossaryTerm[] | TriggerPhrase[] | NegotiationPlaybook[] | CounterpartyTrait[] | ForbiddenPhrase[];

const LISTERS: Record<KnowledgeKind, (f: KnowledgeFilters) => Promise<KnowledgeItem>> = {
  terms: listTerms,
  triggers: listTriggers,
  playbooks: listPlaybooks,
  traits: listTraits,
  forbidden: listForbidden,
};

export function useKnowledgeList(kind: KnowledgeKind, filters: KnowledgeFilters = {}) {
  return useQuery({
    queryKey: knowledgeKeys.list(kind, filters),
    queryFn: () => LISTERS[kind](filters),
  });
}

export function useArchiveKnowledgeItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id }: { kind: KnowledgeKind; id: number }) => archiveItem(kind, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: knowledgeKeys.all }),
  });
}

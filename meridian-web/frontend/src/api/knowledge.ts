import api from './client';
import type {
  GlossaryTerm, TriggerPhrase, NegotiationPlaybook, CounterpartyTrait, ForbiddenPhrase, KnowledgeKind,
} from '../types';

export interface KnowledgeFilters {
  status?: string;
  customer_id?: number;
  object_id?: number;
}

export async function listTerms(f: KnowledgeFilters = {}): Promise<GlossaryTerm[]> {
  const { data } = await api.get<GlossaryTerm[]>('/knowledge/terms', { params: f });
  return data;
}

export async function listTriggers(f: KnowledgeFilters = {}): Promise<TriggerPhrase[]> {
  const { data } = await api.get<TriggerPhrase[]>('/knowledge/triggers', { params: f });
  return data;
}

export async function listPlaybooks(f: KnowledgeFilters = {}): Promise<NegotiationPlaybook[]> {
  const { data } = await api.get<NegotiationPlaybook[]>('/knowledge/playbooks', { params: f });
  return data;
}

export async function listTraits(f: KnowledgeFilters = {}): Promise<CounterpartyTrait[]> {
  const { data } = await api.get<CounterpartyTrait[]>('/knowledge/traits', { params: f });
  return data;
}

export async function listForbidden(f: KnowledgeFilters = {}): Promise<ForbiddenPhrase[]> {
  const { data } = await api.get<ForbiddenPhrase[]>('/knowledge/forbidden', { params: f });
  return data;
}

export async function archiveItem(kind: KnowledgeKind, id: number): Promise<void> {
  await api.post(`/knowledge/${kind}/${id}/archive`);
}

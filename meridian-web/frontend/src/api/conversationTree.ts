import api from './client';
import type { ConversationTree, ConversationTopic, ConversationTopicUpdateInput } from '../types';

export async function getConversationTree(meetingId: number): Promise<ConversationTree> {
  const { data } = await api.get<ConversationTree>(`/meetings/${meetingId}/conversation-tree`);
  return data;
}

export async function updateConversationTopic(
  meetingId: number, topicId: number, patch: ConversationTopicUpdateInput,
): Promise<ConversationTopic> {
  const { data } = await api.patch<ConversationTopic>(
    `/meetings/${meetingId}/conversation-tree/${topicId}`, patch,
  );
  return data;
}

export async function refineConversationTree(meetingId: number): Promise<ConversationTree> {
  const { data } = await api.post<ConversationTree>(`/meetings/${meetingId}/conversation-tree/refine`);
  return data;
}

export async function rebuildConversationTree(meetingId: number): Promise<ConversationTree> {
  const { data } = await api.post<ConversationTree>(`/meetings/${meetingId}/conversation-tree/rebuild`);
  return data;
}

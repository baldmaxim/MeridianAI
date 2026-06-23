import { useState, useEffect } from 'react';
import { useAuth } from './hooks/useAuth';
import { LoginPage } from './pages/LoginPage';
import { MeetingPage } from './pages/MeetingPage';
import { HistoryPage } from './pages/HistoryPage';
import { MeetingDetailPage } from './pages/MeetingDetailPage';
import { BatchPage } from './pages/BatchPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { AISettingsPage } from './pages/AISettingsPage';
import { ObjectsPage } from './pages/ObjectsPage';
import { ObjectDetailPage } from './pages/ObjectDetailPage';
import { LettersSearchPage } from './pages/LettersSearchPage';
import { ProjectLinkPage } from './pages/ProjectLinkPage';
import { SettingsHubPage } from './pages/SettingsHubPage';
import { AppLayout } from './components/layout/AppLayout';
import { PageTransition } from './components/common/PageTransition';
import { RecorderPage } from './pages/RecorderPage';
import { MobileMeetingsPage } from './pages/mobile/MobileMeetingsPage';
import { MobileMeetingDetailPage } from './pages/mobile/MobileMeetingDetailPage';
import { usePathname, parseRoute, navigate, paths } from './lib/navigation';
import { useMeetingStore } from './store/meetingStore';
import { createMeeting } from './api/meetings';
import { meetingDisplayName } from './lib/meetingName';
import type { ProjectObject } from './types';

type Page = 'objects' | 'object-detail' | 'meeting' | 'history' | 'history-detail' | 'batch'
  | 'knowledge' | 'letters' | 'project-links' | 'ai-settings' | 'settings';

// Под-потоки, всегда доступные авторизованному (не входят в матрицу доступа).
const ALWAYS_PAGES: Page[] = ['objects', 'object-detail', 'meeting', 'history', 'history-detail', 'letters', 'project-links'];

// Маршрут (URL) → внутренняя страница + выбранные сущности.
function pageFromRoute(route: ReturnType<typeof parseRoute>): {
  page: Page;
  objectId: number | null;
  meetingId: number | null;
  detailReturn: 'history' | 'object-detail';
} {
  switch (route.kind) {
    case 'object-detail':
      return { page: 'object-detail', objectId: route.objectId, meetingId: null, detailReturn: 'history' };
    case 'meeting':
      return { page: 'meeting', objectId: null, meetingId: route.meetingId ?? null, detailReturn: 'history' };
    case 'history':
      return { page: 'history', objectId: null, meetingId: null, detailReturn: 'history' };
    case 'meeting-detail':
      return {
        page: 'history-detail',
        objectId: route.objectId ?? null,
        meetingId: route.meetingId,
        detailReturn: route.from === 'object' ? 'object-detail' : 'history',
      };
    case 'batch':
      return { page: 'batch', objectId: null, meetingId: null, detailReturn: 'history' };
    case 'knowledge':
      return { page: 'knowledge', objectId: null, meetingId: null, detailReturn: 'history' };
    case 'letters':
      return { page: 'letters', objectId: null, meetingId: null, detailReturn: 'history' };
    case 'project-links':
      return { page: 'project-links', objectId: null, meetingId: null, detailReturn: 'history' };
    case 'ai-settings':
      return { page: 'ai-settings', objectId: null, meetingId: null, detailReturn: 'history' };
    case 'settings':
      return { page: 'settings', objectId: null, meetingId: null, detailReturn: 'history' };
    default:
      return { page: 'objects', objectId: null, meetingId: null, detailReturn: 'history' };
  }
}

function App() {
  const { user, loading, login, register, logout } = useAuth();
  const [viewAsUser, setViewAsUser] = useState(false);
  const pathname = usePathname();
  const route = parseRoute(pathname);

  // После входа со стартовой/логин-страницы — на список объектов.
  useEffect(() => {
    if (user && (route.kind === 'login')) navigate(paths.objects);
  }, [user, route.kind]);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#080A0F', color: '#EDF2FF' }}>
        Загрузка...
      </div>
    );
  }

  // Авторизация: при заходе на любой адрес без токена показываем логин;
  // pathname сохраняется → после входа рендерится исходный маршрут.
  if (!user) {
    return <LoginPage onLogin={login} onRegister={register} />;
  }

  // Мобильные маршруты по URL (для прямых ссылок/QR)
  if (route.kind === 'recorder') {
    return <RecorderPage meetingId={route.meetingId} />;
  }
  if (route.kind === 'mobile-list') {
    return <MobileMeetingsPage userName={user.display_name || user.email} onLogout={logout} />;
  }
  if (route.kind === 'mobile-detail') {
    return <MobileMeetingDetailPage meetingId={route.meetingId} />;
  }

  const { page: currentPage, objectId: selectedObjectId, meetingId: selectedMeetingId, detailReturn } = pageFromRoute(route);

  const isAdmin = user.role === 'admin';
  const effectiveAdmin = isAdmin && !viewAsUser;

  // Активный набор доступных страниц (page-access): реальный пользователь → его роль;
  // админ в режиме «смотреть как пользователь» → набор роли user.
  const activePages = new Set<string>(
    isAdmin
      ? (viewAsUser ? (user.user_role_pages ?? []) : (user.allowed_pages ?? []))
      : (user.allowed_pages ?? [])
  );
  const canAccess = (key: string) => activePages.has(key);

  const openObject = (id: number) => navigate(paths.objectDetail(id));

  // «Новая встреча» — ЯВНОЕ действие: сразу создаём встречу в БД (POST), чтобы у неё был
  // id, рабочая комната и ссылка для подключения других устройств — ещё ДО старта записи.
  // (Открытие/reload портала по-прежнему ничего не создаёт — только этот клик.)
  const startNewMeeting = async (obj: ProjectObject) => {
    const store = useMeetingStore.getState();
    store.newMeetingSession();
    store.setSelectedCustomerId(obj.customer_id);
    store.setSelectedObjectId(obj.id);
    store.setSelectedCustomerName(obj.customer_name);
    store.setSelectedObjectName(obj.name);
    const title = meetingDisplayName({
      customer_name: obj.customer_name,
      object_name: obj.name,
      started_at: new Date().toISOString(),
    });
    store.setMeetingName(title);
    try {
      const m = await createMeeting({
        customer_id: obj.customer_id,
        object_id: obj.id,
        title: title || null,
      });
      store.setDraftMeetingId(m.id);
      store.setCurrentMeetingId(m.id);
      store.setMeetingStartedAt(m.started_at);
      navigate(paths.meetingRoom(m.id));
    } catch {
      // Не удалось создать — открываем черновик (запись создаст встречу как fallback).
      store.setMeetingName(title);
      navigate(paths.meeting);
    }
  };

  const onToggleViewAs = () => {
    const next = !viewAsUser;
    setViewAsUser(next);
    if (next) {
      // Уходим со страницы, недоступной роли user, чтобы превью было консистентным.
      const userPages = new Set<string>(user.user_role_pages ?? []);
      const reachable = ALWAYS_PAGES.includes(currentPage) || userPages.has(currentPage);
      if (!reachable) navigate(paths.objects);
    }
  };

  const objectsPage = (
    <ObjectsPage onOpenObject={openObject} />
  );

  const renderPage = () => {
    // Гард доступа по матрице. Реальный админ всегда видит settings (анти-локаут).
    if (!ALWAYS_PAGES.includes(currentPage)) {
      const hardAllow = effectiveAdmin && currentPage === 'settings';
      if (!canAccess(currentPage) && !hardAllow) return objectsPage;
    }
    switch (currentPage) {
      case 'objects':
        return objectsPage;
      case 'object-detail':
        return (
          <ObjectDetailPage
            objectId={selectedObjectId!}
            onBack={() => navigate(paths.objects)}
            onOpenMeeting={(id) => navigate(paths.meetingDetail(id, 'object', selectedObjectId!))}
            onOpenLiveMeeting={(id) => {
              const st = useMeetingStore.getState();
              st.setSelectedObjectId(selectedObjectId!);
              st.setCurrentMeetingId(id);
              navigate(paths.meetingRoom(id));
            }}
            onNewMeeting={startNewMeeting}
          />
        );
      case 'settings':
        return <SettingsHubPage onBack={() => navigate(paths.objects)} />;
      case 'meeting':
        return (
          <MeetingPage
            meetingId={selectedMeetingId ?? undefined}
            onBack={() => {
              const objId = useMeetingStore.getState().selectedObjectId;
              navigate(objId != null ? paths.objectDetail(objId) : paths.objects);
            }}
          />
        );
      case 'batch':
        return <BatchPage onBack={() => navigate(paths.objects)} />;
      case 'knowledge':
        return <KnowledgePage onBack={() => navigate(paths.objects)} />;
      case 'letters':
        return <LettersSearchPage onBack={() => navigate(paths.objects)} />;
      case 'project-links':
        return <ProjectLinkPage onBack={() => navigate(paths.letters)} />;
      case 'ai-settings':
        return <AISettingsPage onBack={() => navigate(paths.objects)} />;
      case 'history':
        return (
          <HistoryPage
            onBack={() => navigate(paths.objects)}
            onSelectMeeting={(id) => navigate(paths.meetingDetail(id))}
          />
        );
      case 'history-detail':
        return (
          <MeetingDetailPage
            meetingId={selectedMeetingId!}
            backLabel={detailReturn === 'object-detail' ? 'К объекту' : 'К истории'}
            onBack={() => navigate(detailReturn === 'object-detail' && selectedObjectId != null
              ? paths.objectDetail(selectedObjectId)
              : paths.history)}
            onContinue={() => {
              useMeetingStore.getState().setCurrentMeetingId(selectedMeetingId!);
              navigate(paths.meetingRoom(selectedMeetingId!));
            }}
          />
        );
      default:
        return objectsPage;
    }
  };

  return (
    <AppLayout
      userName={user.display_name || user.email}
      onLogout={() => { logout(); navigate(paths.login); }}
      onShowObjects={() => navigate(paths.objects)}
      showObjects={currentPage === 'objects' || currentPage === 'object-detail'}
      onShowSettings={canAccess('settings') ? () => navigate(currentPage === 'settings' ? paths.objects : paths.settings) : undefined}
      showSettings={currentPage === 'settings'}
      onShowBatch={canAccess('batch') ? () => navigate(currentPage === 'batch' ? paths.objects : paths.batch) : undefined}
      showBatch={currentPage === 'batch'}
      onShowKnowledge={canAccess('knowledge') ? () => navigate(currentPage === 'knowledge' ? paths.objects : paths.knowledge) : undefined}
      showKnowledge={currentPage === 'knowledge'}
      onShowLetters={() => navigate(currentPage === 'letters' ? paths.objects : paths.letters)}
      showLetters={currentPage === 'letters'}
      onShowAISettings={canAccess('ai-settings') ? () => navigate(currentPage === 'ai-settings' ? paths.objects : paths.aiSettings) : undefined}
      showAISettings={currentPage === 'ai-settings'}
      canSwitchRole={isAdmin}
      viewAsUser={viewAsUser}
      onToggleViewAs={onToggleViewAs}
      inMeeting={currentPage === 'meeting'}
      inObjectDetail={currentPage === 'object-detail'}
    >
      <PageTransition
        routeKey={`${currentPage}:${selectedObjectId ?? ''}:${selectedMeetingId ?? ''}`}
        style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
      >
        {renderPage()}
      </PageTransition>
    </AppLayout>
  );
}

export default App;

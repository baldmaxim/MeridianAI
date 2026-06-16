import { useState, useEffect } from 'react';
import { useAuth } from './hooks/useAuth';
import { LoginPage } from './pages/LoginPage';
import { MeetingPage } from './pages/MeetingPage';
import { HistoryPage } from './pages/HistoryPage';
import { MeetingDetailPage } from './pages/MeetingDetailPage';
import { BatchPage } from './pages/BatchPage';
import { DirectoryPage } from './pages/DirectoryPage';
import type { DirSection } from './pages/DirectoryPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { AISettingsPage } from './pages/AISettingsPage';
import { ObjectsPage } from './pages/ObjectsPage';
import { ObjectDetailPage } from './pages/ObjectDetailPage';
import { SettingsHubPage } from './pages/SettingsHubPage';
import { AppLayout } from './components/layout/AppLayout';
import { RecorderPage } from './pages/RecorderPage';
import { MobileMeetingsPage } from './pages/mobile/MobileMeetingsPage';
import { MobileMeetingDetailPage } from './pages/mobile/MobileMeetingDetailPage';
import { usePathname, parseRoute } from './lib/navigation';
import { useMeetingStore } from './store/meetingStore';
import { createMeeting } from './api/meetings';
import type { ProjectObject } from './types';

type Page = 'objects' | 'object-detail' | 'meeting' | 'history' | 'history-detail' | 'batch'
  | 'directory' | 'dir-objects' | 'dir-departments' | 'knowledge' | 'ai-settings' | 'settings';

// Под-потоки, всегда доступные авторизованному (не входят в матрицу доступа).
const ALWAYS_PAGES: Page[] = ['objects', 'object-detail', 'meeting', 'history', 'history-detail'];

// Подстраницы справочника ↔ ключи каталога page-access.
const DIR_PAGE_BY_SECTION: Record<DirSection, Page> = {
  objects: 'dir-objects',
  departments: 'dir-departments',
};
const DIR_SECTIONS: DirSection[] = ['objects', 'departments'];

function App() {
  const { user, loading, login, register, logout } = useAuth();
  const [currentPage, setCurrentPage] = useState<Page>('objects');
  const [selectedMeetingId, setSelectedMeetingId] = useState<number | null>(null);
  const [selectedObjectId, setSelectedObjectId] = useState<number | null>(null);
  const [detailReturn, setDetailReturn] = useState<'history' | 'object-detail'>('history');
  const [viewAsUser, setViewAsUser] = useState(false);
  const pathname = usePathname();
  const route = parseRoute(pathname);

  // Единый слайдер роли управляет и видом встречи: Админ → полный, Пользователь → простой.
  useEffect(() => {
    const eff = user?.role === 'admin' && !viewAsUser;
    useMeetingStore.getState().setUiMode(eff ? 'full' : 'simple');
  }, [user, viewAsUser]);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#080A0F', color: '#EDF2FF' }}>
        Загрузка...
      </div>
    );
  }

  // Авторизация: при заходе на mobile/recorder без токена показываем логин;
  // pathname сохраняется → после входа рендерится исходный маршрут.
  if (!user) {
    return <LoginPage onLogin={login} onRegister={register} />;
  }

  // Этап 3: мобильные маршруты по URL (для прямых ссылок/QR)
  if (route.kind === 'recorder') {
    return <RecorderPage meetingId={route.meetingId} />;
  }
  if (route.kind === 'mobile-list') {
    return <MobileMeetingsPage userName={user.display_name || user.email} onLogout={logout} />;
  }
  if (route.kind === 'mobile-detail') {
    return <MobileMeetingDetailPage meetingId={route.meetingId} />;
  }

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
  const dirSections = DIR_SECTIONS.filter((s) => canAccess(DIR_PAGE_BY_SECTION[s]));
  const canDirectory = dirSections.length > 0;

  const openObject = (id: number) => { setSelectedObjectId(id); setCurrentPage('object-detail'); };

  // Открыть существующую встречу — переиспользуем read-only детальную страницу (с «Продолжить»).
  const openMeetingDetail = (id: number) => {
    setSelectedMeetingId(id);
    setDetailReturn('object-detail');
    setCurrentPage('history-detail');
  };

  // Создать новую встречу под объект и открыть окно встречи.
  const startNewMeeting = async (obj: ProjectObject) => {
    const store = useMeetingStore.getState();
    store.newMeetingSession();
    store.setSelectedCustomerId(obj.customer_id);
    store.setSelectedObjectId(obj.id);
    store.setMeetingName('');
    try {
      const m = await createMeeting({ customer_id: obj.customer_id, object_id: obj.id });
      store.setDraftMeetingId(m.id);
      store.setCurrentMeetingId(m.id);
    } catch {
      // draft не создан — MeetingPage подключится через legacy endpoint
    }
    setCurrentPage('meeting');
  };

  const onToggleViewAs = () => {
    const next = !viewAsUser;
    setViewAsUser(next);
    if (next) {
      // Уходим со страницы, недоступной роли user, чтобы превью было консистентным.
      const userPages = new Set<string>(user.user_role_pages ?? []);
      const reachable = ALWAYS_PAGES.includes(currentPage)
        || (currentPage === 'directory'
          ? DIR_SECTIONS.some((s) => userPages.has(DIR_PAGE_BY_SECTION[s]))
          : userPages.has(currentPage));
      if (!reachable) setCurrentPage('objects');
    }
  };

  const objectsPage = (
    <ObjectsPage onOpenObject={openObject} />
  );

  const renderPage = () => {
    // Гард доступа по матрице. Реальный админ всегда видит settings (анти-локаут).
    if (!ALWAYS_PAGES.includes(currentPage)) {
      const hardAllow = effectiveAdmin && currentPage === 'settings';
      const ok = currentPage === 'directory' ? canDirectory : canAccess(currentPage);
      if (!ok && !hardAllow) return objectsPage;
    }
    switch (currentPage) {
      case 'objects':
        return objectsPage;
      case 'object-detail':
        return (
          <ObjectDetailPage
            objectId={selectedObjectId!}
            onBack={() => setCurrentPage('objects')}
            onOpenMeeting={openMeetingDetail}
            onNewMeeting={startNewMeeting}
          />
        );
      case 'settings':
        return <SettingsHubPage onBack={() => setCurrentPage('objects')} />;
      case 'meeting':
        return <MeetingPage />;
      case 'batch':
        return <BatchPage onBack={() => setCurrentPage('objects')} />;
      case 'directory':
        return (
          <DirectoryPage
            onBack={() => setCurrentPage('objects')}
            onOpenSection={(s) => setCurrentPage(DIR_PAGE_BY_SECTION[s])}
            accessible={dirSections}
          />
        );
      case 'dir-objects':
        return (
          <DirectoryPage
            section="objects"
            onBack={() => setCurrentPage('objects')}
            onBackToHub={() => setCurrentPage('directory')}
          />
        );
      case 'dir-departments':
        return (
          <DirectoryPage
            section="departments"
            onBack={() => setCurrentPage('objects')}
            onBackToHub={() => setCurrentPage('directory')}
          />
        );
      case 'knowledge':
        return <KnowledgePage onBack={() => setCurrentPage('objects')} />;
      case 'ai-settings':
        return <AISettingsPage onBack={() => setCurrentPage('objects')} />;
      case 'history':
        return (
          <HistoryPage
            onBack={() => setCurrentPage('objects')}
            onSelectMeeting={(id) => {
              setSelectedMeetingId(id);
              setDetailReturn('history');
              setCurrentPage('history-detail');
            }}
          />
        );
      case 'history-detail':
        return (
          <MeetingDetailPage
            meetingId={selectedMeetingId!}
            backLabel={detailReturn === 'object-detail' ? 'К объекту' : 'К истории'}
            onBack={() => setCurrentPage(detailReturn === 'object-detail' ? 'object-detail' : 'history')}
            onContinue={() => setCurrentPage('meeting')}
          />
        );
      default:
        return objectsPage;
    }
  };

  return (
    <AppLayout
      userName={user.display_name || user.email}
      onLogout={logout}
      onShowObjects={() => setCurrentPage('objects')}
      showObjects={currentPage === 'objects' || currentPage === 'object-detail'}
      onShowSettings={canAccess('settings') ? () => setCurrentPage(currentPage === 'settings' ? 'objects' : 'settings') : undefined}
      showSettings={currentPage === 'settings'}
      onShowBatch={canAccess('batch') ? () => setCurrentPage(currentPage === 'batch' ? 'objects' : 'batch') : undefined}
      showBatch={currentPage === 'batch'}
      onShowDirectory={canDirectory ? () => setCurrentPage(currentPage === 'directory' ? 'objects' : 'directory') : undefined}
      showDirectory={currentPage === 'directory' || currentPage === 'dir-objects' || currentPage === 'dir-departments'}
      onShowKnowledge={canAccess('knowledge') ? () => setCurrentPage(currentPage === 'knowledge' ? 'objects' : 'knowledge') : undefined}
      showKnowledge={currentPage === 'knowledge'}
      onShowAISettings={canAccess('ai-settings') ? () => setCurrentPage(currentPage === 'ai-settings' ? 'objects' : 'ai-settings') : undefined}
      showAISettings={currentPage === 'ai-settings'}
      canSwitchRole={isAdmin}
      viewAsUser={viewAsUser}
      onToggleViewAs={onToggleViewAs}
    >
      {renderPage()}
    </AppLayout>
  );
}

export default App;

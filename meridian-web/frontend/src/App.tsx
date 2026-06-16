import { useState, useEffect } from 'react';
import { useAuth } from './hooks/useAuth';
import { LoginPage } from './pages/LoginPage';
import { MeetingPage } from './pages/MeetingPage';
import { HistoryPage } from './pages/HistoryPage';
import { MeetingDetailPage } from './pages/MeetingDetailPage';
import { BatchPage } from './pages/BatchPage';
import { DirectoryPage } from './pages/DirectoryPage';
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

type Page = 'objects' | 'object-detail' | 'meeting' | 'history' | 'history-detail' | 'batch' | 'directory' | 'knowledge' | 'ai-settings' | 'settings';

// Разделы только для админа (скрыты у обычного пользователя и в режиме «смотреть как пользователь»).
const ADMIN_PAGES: Page[] = ['settings', 'directory', 'knowledge', 'ai-settings'];

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
    if (next && ADMIN_PAGES.includes(currentPage)) setCurrentPage('objects');
  };

  const objectsPage = (
    <ObjectsPage onOpenObject={openObject} />
  );

  const renderPage = () => {
    // Защита: админ-страница недоступна без прав — отдаём список объектов.
    if (ADMIN_PAGES.includes(currentPage) && !effectiveAdmin) return objectsPage;
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
        return <DirectoryPage onBack={() => setCurrentPage('objects')} />;
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
      onShowSettings={effectiveAdmin ? () => setCurrentPage(currentPage === 'settings' ? 'objects' : 'settings') : undefined}
      showSettings={currentPage === 'settings'}
      onShowBatch={() => setCurrentPage(currentPage === 'batch' ? 'objects' : 'batch')}
      showBatch={currentPage === 'batch'}
      onShowDirectory={effectiveAdmin ? () => setCurrentPage(currentPage === 'directory' ? 'objects' : 'directory') : undefined}
      showDirectory={currentPage === 'directory'}
      onShowKnowledge={effectiveAdmin ? () => setCurrentPage(currentPage === 'knowledge' ? 'objects' : 'knowledge') : undefined}
      showKnowledge={currentPage === 'knowledge'}
      onShowAISettings={effectiveAdmin ? () => setCurrentPage(currentPage === 'ai-settings' ? 'objects' : 'ai-settings') : undefined}
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

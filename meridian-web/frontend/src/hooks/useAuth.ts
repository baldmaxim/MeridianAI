import { useState, useEffect, useCallback } from 'react';
import type { User } from '../types';
import { login as apiLogin, register as apiRegister, getMe } from '../api/auth';
import { queryClient } from '../lib/queryClient';
import { authKeys } from './queries/auth';
import { API_CACHE_NAME } from '../lib/swCache';

// SSO session bridging: callback вернул локальный JWT во fragment (#sso_token=...).
// Идемпотентна: после первого вызова hash очищен.
function consumeSsoToken() {
  const m = window.location.hash.match(/sso_token=([^&]+)/);
  if (m) {
    localStorage.setItem('token', decodeURIComponent(m[1]));
    history.replaceState(null, '', window.location.pathname + window.location.search);
  }
}

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  // Без токена загрузка не нужна — сразу false (без setState в эффекте).
  const [loading, setLoading] = useState(() => {
    consumeSsoToken();
    return !!localStorage.getItem('token');
  });

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      getMe()
        .then((me) => {
          queryClient.setQueryData(authKeys.me, me); // засеять кэш → useMe не дёргает /auth/me повторно
          setUser(me);
        })
        .catch(() => {
          localStorage.removeItem('token');
          queryClient.clear();
          setUser(null);
        })
        .finally(() => setLoading(false));
    }
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiLogin(email, password);
    localStorage.setItem('token', res.access_token);
    queryClient.clear(); // сбросить кэш предыдущей сессии (защита от показа чужих данных)
    const me = await getMe();
    queryClient.setQueryData(authKeys.me, me);
    setUser(me);
    return me;
  }, []);

  const register = useCallback(async (email: string, password: string, displayName?: string, department?: string) => {
    const res = await apiRegister(email, password, displayName, department);
    localStorage.setItem('token', res.access_token);
    queryClient.clear();
    const me = await getMe();
    queryClient.setQueryData(authKeys.me, me);
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    queryClient.clear(); // очистить весь кэш данных при выходе
    // SW-кэш GET /api/* (NetworkFirst) не привязан к пользователю — сбрасываем, чтобы следующий вход не увидел чужое
    if ('caches' in window) void caches.delete(API_CACHE_NAME).catch(() => false);
    setUser(null);
  }, []);

  return { user, loading, login, register, logout };
}

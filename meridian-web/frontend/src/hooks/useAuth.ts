import { useState, useEffect, useCallback } from 'react';
import type { User } from '../types';
import { login as apiLogin, register as apiRegister, getMe } from '../api/auth';
import { queryClient } from '../lib/queryClient';
import { authKeys } from './queries/auth';

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // SSO session bridging: callback вернул локальный JWT во fragment (#sso_token=...)
    const m = window.location.hash.match(/sso_token=([^&]+)/);
    if (m) {
      localStorage.setItem('token', decodeURIComponent(m[1]));
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
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
    } else {
      setLoading(false);
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
    setUser(null);
  }, []);

  return { user, loading, login, register, logout };
}

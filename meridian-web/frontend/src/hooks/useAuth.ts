import { useState, useEffect, useCallback } from 'react';
import type { User } from '../types';
import { login as apiLogin, register as apiRegister, getMe } from '../api/auth';

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      getMe()
        .then(setUser)
        .catch(() => {
          localStorage.removeItem('token');
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
    const me = await getMe();
    setUser(me);
    return me;
  }, []);

  const register = useCallback(async (email: string, password: string, displayName?: string) => {
    const res = await apiRegister(email, password, displayName);
    localStorage.setItem('token', res.access_token);
    const me = await getMe();
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    setUser(null);
  }, []);

  return { user, loading, login, register, logout };
}

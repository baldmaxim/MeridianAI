export interface User {
  id: number;
  email: string;
  role: 'user' | 'admin';
  display_name: string | null;
  department: string | null;
  is_active: boolean;
  // Доступные роли страницы (ключи каталога) — приходят из /auth/me.
  allowed_pages: string[];
  // Набор роли "user" — для превью «смотреть как пользователь» (только у админа).
  user_role_pages?: string[];
}

// --- Доступ к страницам по ролям (page-access) ---

export interface PageCatalogItem {
  key: string;
  label: string;
}

export interface RolePageAccess {
  role_name: string;
  allowed_pages: string[];
}

export interface PageAccessConfig {
  catalog: PageCatalogItem[];
  roles: RolePageAccess[];
  locked: Record<string, string[]>;
}

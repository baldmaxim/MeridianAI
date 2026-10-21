/** Действие навигации шапки: адрес (для Ctrl/⌘-клика), обработчик и признак активной страницы. */
export interface IHeaderAction {
  path: string;
  onClick: () => void;
  active: boolean;
}

/** Модель навигации шапки: ключ присутствует, только если раздел доступен пользователю. */
export interface IHeaderNavModel {
  objects?: IHeaderAction;
  letters?: IHeaderAction;
  knowledge?: IHeaderAction;
  files?: IHeaderAction;
  batch?: IHeaderAction;
  desktop?: IHeaderAction;
  /** Шестерёнка «Настройки»: хаб настроек, а если его нет — AI-профили */
  settings?: IHeaderAction;
}

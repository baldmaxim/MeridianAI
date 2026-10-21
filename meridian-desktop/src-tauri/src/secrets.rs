//! Секреты (токен устройства, API-ключи) лежат в хранилище ОС: Windows Credential
//! Manager, macOS Keychain, Linux Secret Service. Сервис `ru.meridianai.desktop`.
//! Хранилище спрятано за трейтом `SecretBackend`, чтобы тесты шли на памяти, а не
//! в настоящем keyring. Значения секретов нигде не логируются.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};
use std::time::{Duration, Instant};

use log::warn;

/// Имя сервиса в хранилище ОС.
pub const KEYRING_SERVICE: &str = "ru.meridianai.desktop";

/// После сбоя хранилища его не дёргают столько времени: лог не засоряется,
/// а вызывающий код не ждёт таймаута D-Bus на каждое чтение настроек.
const FAILURE_COOLDOWN: Duration = Duration::from_secs(30);

pub trait SecretBackend: Send + Sync {
    /// `Ok(None)` — записи нет. Текст ошибки не содержит значения секрета.
    fn get(&self, name: &str) -> Result<Option<String>, String>;
    fn set(&self, name: &str, value: &str) -> Result<(), String>;
    /// Удаление отсутствующей записи — не ошибка.
    fn delete(&self, name: &str) -> Result<(), String>;
}

/// Настоящее хранилище ОС через крейт `keyring`.
pub struct KeyringBackend;

impl KeyringBackend {
    fn entry(name: &str) -> Result<keyring::Entry, String> {
        keyring::Entry::new(KEYRING_SERVICE, name).map_err(|e| e.to_string())
    }
}

impl SecretBackend for KeyringBackend {
    fn get(&self, name: &str) -> Result<Option<String>, String> {
        match Self::entry(name)?.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }

    fn set(&self, name: &str, value: &str) -> Result<(), String> {
        Self::entry(name)?
            .set_password(value)
            .map_err(|e| e.to_string())
    }

    fn delete(&self, name: &str) -> Result<(), String> {
        match Self::entry(name)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(e.to_string()),
        }
    }
}

/// Обёртка с кэшем: хранилище ОС читается один раз на имя за запуск
/// (`get_settings` зовут часто), повторная запись того же значения пропускается.
pub struct SecretStore {
    backend: Arc<dyn SecretBackend>,
    cooldown: Duration,
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    /// `Some(None)` — в хранилище записи точно нет.
    cache: HashMap<String, Option<String>>,
    failed_at: Option<Instant>,
}

impl SecretStore {
    pub fn new(backend: Arc<dyn SecretBackend>) -> Self {
        Self::with_cooldown(backend, FAILURE_COOLDOWN)
    }

    pub fn with_cooldown(backend: Arc<dyn SecretBackend>, cooldown: Duration) -> Self {
        Self {
            backend,
            cooldown,
            state: Mutex::new(State::default()),
        }
    }

    fn state(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Выполняет вызов бэкенда с паузой после сбоя. Сообщение в лог — только
    /// первое за паузу и без значения секрета.
    fn call<T>(
        &self,
        name: &str,
        op: &str,
        f: impl FnOnce(&dyn SecretBackend) -> Result<T, String>,
    ) -> Result<T, String> {
        {
            let state = self.state();
            if let Some(at) = state.failed_at {
                if at.elapsed() < self.cooldown {
                    return Err("хранилище секретов недоступно".to_string());
                }
            }
        }
        // Вызов бэкенда вне мьютекса: D-Bus/Keychain могут блокироваться.
        let result = f(self.backend.as_ref());
        let mut state = self.state();
        match &result {
            Ok(_) => state.failed_at = None,
            Err(e) => {
                state.failed_at = Some(Instant::now());
                warn!("Хранилище секретов недоступно ({op} '{name}'): {e}");
            }
        }
        result
    }

    pub fn get(&self, name: &str) -> Result<Option<String>, String> {
        if let Some(cached) = self.state().cache.get(name) {
            return Ok(cached.clone());
        }
        let value = self.call(name, "чтение", |b| b.get(name))?;
        self.state().cache.insert(name.to_string(), value.clone());
        Ok(value)
    }

    pub fn set(&self, name: &str, value: &str) -> Result<(), String> {
        if self.state().cache.get(name) == Some(&Some(value.to_string())) {
            return Ok(());
        }
        self.call(name, "запись", |b| b.set(name, value))?;
        self.state()
            .cache
            .insert(name.to_string(), Some(value.to_string()));
        Ok(())
    }

    pub fn delete(&self, name: &str) -> Result<(), String> {
        self.call(name, "удаление", |b| b.delete(name))?;
        self.state().cache.insert(name.to_string(), None);
        Ok(())
    }

    /// Удаляет запись, только если известно, что она есть (читали или писали).
    /// Не вызывает хранилище зря и не стирает ключ, который не удалось прочитать.
    pub fn delete_if_known(&self, name: &str) -> Result<(), String> {
        if matches!(self.state().cache.get(name), Some(Some(_))) {
            self.delete(name)
        } else {
            Ok(())
        }
    }
}

/// Общий для процесса экземпляр на настоящем хранилище ОС.
pub fn global() -> &'static Arc<SecretStore> {
    static STORE: OnceLock<Arc<SecretStore>> = OnceLock::new();
    STORE.get_or_init(|| Arc::new(SecretStore::new(Arc::new(KeyringBackend))))
}

#[cfg(test)]
pub mod testing {
    use super::*;
    use std::sync::atomic::{AtomicBool, Ordering};

    /// Хранилище в памяти; `fail` имитирует недоступный keyring.
    #[derive(Default)]
    pub struct MemoryBackend {
        pub items: Mutex<HashMap<String, String>>,
        pub fail: AtomicBool,
    }

    impl MemoryBackend {
        pub fn failing() -> Arc<Self> {
            let backend = Self::default();
            backend.fail.store(true, Ordering::SeqCst);
            Arc::new(backend)
        }

        pub fn stored(&self, name: &str) -> Option<String> {
            self.items.lock().unwrap().get(name).cloned()
        }

        fn check(&self) -> Result<(), String> {
            if self.fail.load(Ordering::SeqCst) {
                Err("keyring недоступен".to_string())
            } else {
                Ok(())
            }
        }
    }

    impl SecretBackend for MemoryBackend {
        fn get(&self, name: &str) -> Result<Option<String>, String> {
            self.check()?;
            Ok(self.items.lock().unwrap().get(name).cloned())
        }

        fn set(&self, name: &str, value: &str) -> Result<(), String> {
            self.check()?;
            self.items
                .lock()
                .unwrap()
                .insert(name.to_string(), value.to_string());
            Ok(())
        }

        fn delete(&self, name: &str) -> Result<(), String> {
            self.check()?;
            self.items.lock().unwrap().remove(name);
            Ok(())
        }
    }

    /// Хранилище на памяти без паузы после сбоя.
    pub fn store_with(backend: &Arc<MemoryBackend>) -> Arc<SecretStore> {
        Arc::new(SecretStore::with_cooldown(backend.clone(), Duration::ZERO))
    }
}

#[cfg(test)]
mod tests {
    use super::testing::*;
    use super::*;
    use std::sync::atomic::Ordering;

    #[test]
    fn set_get_delete_roundtrip() {
        let backend = Arc::new(MemoryBackend::default());
        let store = store_with(&backend);
        assert_eq!(store.get("a").unwrap(), None);
        store.set("a", "v1").unwrap();
        assert_eq!(backend.stored("a").as_deref(), Some("v1"));
        assert_eq!(store.get("a").unwrap().as_deref(), Some("v1"));
        store.delete("a").unwrap();
        assert_eq!(backend.stored("a"), None);
        assert_eq!(store.get("a").unwrap(), None);
    }

    #[test]
    fn reads_are_cached() {
        let backend = Arc::new(MemoryBackend::default());
        backend.items.lock().unwrap().insert("a".into(), "v".into());
        let store = store_with(&backend);
        assert_eq!(store.get("a").unwrap().as_deref(), Some("v"));
        // Хранилище упало, но кэш отвечает.
        backend.fail.store(true, Ordering::SeqCst);
        assert_eq!(store.get("a").unwrap().as_deref(), Some("v"));
    }

    #[test]
    fn failure_is_reported_and_cooldown_skips_backend() {
        let backend = MemoryBackend::failing();
        let store = Arc::new(SecretStore::new(backend.clone()));
        assert!(store.get("a").is_err());
        // В паузе даже после «починки» бэкенда хранилище не дёргают.
        backend.fail.store(false, Ordering::SeqCst);
        assert!(store.set("a", "v").is_err());
        assert_eq!(backend.stored("a"), None);
    }

    #[test]
    fn delete_if_known_does_not_touch_unread_entries() {
        let backend = Arc::new(MemoryBackend::default());
        backend.items.lock().unwrap().insert("a".into(), "v".into());
        let store = store_with(&backend);
        store.delete_if_known("a").unwrap();
        assert_eq!(backend.stored("a").as_deref(), Some("v"));
        store.get("a").unwrap();
        store.delete_if_known("a").unwrap();
        assert_eq!(backend.stored("a"), None);
    }
}

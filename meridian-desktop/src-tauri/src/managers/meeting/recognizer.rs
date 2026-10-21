//! The queue between the channels' phrase cutters and the single recognizer.
//!
//! Capture never waits for recognition: phrases pile up here while the engine
//! works through them in order.

use std::collections::VecDeque;
use std::sync::{Condvar, Mutex, MutexGuard};

use anyhow::Result;
use log::{debug, warn};

use super::db::Segment;
use super::segmenter::Phrase;

pub struct PhraseJob {
    /// Label stored on the segment: `mic`, `system` or `mixed`.
    pub channel: String,
    pub phrase: Phrase,
}

#[derive(Default)]
struct QueueState {
    jobs: VecDeque<PhraseJob>,
    closed: bool,
    aborted: bool,
}

#[derive(Default)]
pub struct PhraseQueue {
    state: Mutex<QueueState>,
    ready: Condvar,
}

impl PhraseQueue {
    fn lock(&self) -> MutexGuard<'_, QueueState> {
        self.state.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn push(&self, job: PhraseJob) {
        self.lock().jobs.push_back(job);
        self.ready.notify_one();
    }

    pub fn len(&self) -> usize {
        self.lock().jobs.len()
    }

    /// No more phrases will come; the recognizer ends after the last one.
    pub fn close(&self) {
        self.lock().closed = true;
        self.ready.notify_all();
    }

    /// The recognizer ends after the phrase in progress; the rest is dropped.
    pub fn abort(&self) {
        let mut state = self.lock();
        state.aborted = true;
        let dropped = state.jobs.len();
        state.jobs.clear();
        drop(state);
        if dropped > 0 {
            warn!("{dropped} unrecognized meeting phrases dropped (audio stays on disk)");
        }
        self.ready.notify_all();
    }

    /// The next phrase, waiting for one; `None` once the queue is closed and
    /// empty, or aborted.
    fn pop(&self) -> Option<PhraseJob> {
        let mut state = self.lock();
        loop {
            if state.aborted {
                return None;
            }
            if let Some(job) = state.jobs.pop_front() {
                return Some(job);
            }
            if state.closed {
                return None;
            }
            state = self.ready.wait(state).unwrap_or_else(|e| e.into_inner());
        }
    }

    fn is_aborted(&self) -> bool {
        self.lock().aborted
    }
}

/// Recognizes queued phrases in order until the queue ends. A phrase that
/// fails is reported and skipped; empty text is not stored. `store` gets the
/// phrase's samples too (the voice is told from them).
pub fn run_recognizer(
    queue: &PhraseQueue,
    meeting_id: &str,
    mut transcribe: impl FnMut(&[f32]) -> Result<String>,
    mut store: impl FnMut(Segment, &[f32]) -> Result<()>,
    mut on_error: impl FnMut(String),
    mut new_segment_id: impl FnMut() -> String,
    mut now: impl FnMut() -> String,
) {
    while let Some(job) = queue.pop() {
        let PhraseJob { channel, phrase } = job;
        let text = match transcribe(&phrase.samples) {
            Ok(text) => text.trim().to_string(),
            Err(e) => {
                on_error(format!("Не удалось распознать фразу: {e:#}"));
                continue;
            }
        };
        if text.is_empty() || queue.is_aborted() {
            debug!(
                "Meeting phrase {:.1}-{:.1}s: nothing to store",
                phrase.start, phrase.end
            );
            continue;
        }
        let segment = Segment {
            id: new_segment_id(),
            meeting_id: meeting_id.to_string(),
            channel,
            start_time: phrase.start,
            end_time: phrase.end,
            text,
            created_at: now(),
            synced: false,
            voice: None,
        };
        if let Err(e) = store(segment, &phrase.samples) {
            on_error(format!("Не удалось сохранить фразу: {e:#}"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn job(channel: &str, start: f64) -> PhraseJob {
        PhraseJob {
            channel: channel.to_string(),
            phrase: Phrase {
                samples: vec![start as f32; 4],
                start,
                end: start + 1.0,
            },
        }
    }

    fn collect(queue: &PhraseQueue, fail_on: Option<f32>) -> (Vec<Segment>, Vec<String>) {
        let mut stored = Vec::new();
        let mut errors = Vec::new();
        let mut n = 0;
        run_recognizer(
            queue,
            "m1",
            |samples| match samples[0] {
                x if Some(x) == fail_on => anyhow::bail!("boom"),
                x if x == 2.0 => Ok("   ".to_string()),
                x => Ok(format!(" фраза {x} ")),
            },
            |segment, _| {
                stored.push(segment);
                Ok(())
            },
            |e| errors.push(e),
            || {
                n += 1;
                format!("id{n}")
            },
            || "2026-01-01T00:00:00.000Z".to_string(),
        );
        (stored, errors)
    }

    #[test]
    fn recognizes_in_order_skipping_empty_and_failed() {
        let queue = PhraseQueue::default();
        for (channel, start) in [("mic", 0.0), ("system", 1.0), ("mic", 2.0), ("mic", 3.0)] {
            queue.push(job(channel, start));
        }
        assert_eq!(queue.len(), 4);
        queue.close();

        let (stored, errors) = collect(&queue, Some(1.0));
        assert_eq!(stored.len(), 2, "empty and failed phrases are not stored");
        assert_eq!(stored[0].text, "фраза 0");
        assert_eq!(stored[0].channel, "mic");
        assert_eq!(stored[0].meeting_id, "m1");
        assert_eq!((stored[0].start_time, stored[0].end_time), (0.0, 1.0));
        assert_eq!(stored[1].text, "фраза 3");
        assert_eq!(errors.len(), 1);
        assert!(errors[0].contains("boom"));
        assert_eq!(queue.len(), 0);
    }

    #[test]
    fn waits_for_phrases_and_ends_when_closed() {
        let queue = Arc::new(PhraseQueue::default());
        let worker = {
            let queue = Arc::clone(&queue);
            std::thread::spawn(move || collect(&queue, None).0.len())
        };
        std::thread::sleep(std::time::Duration::from_millis(50));
        queue.push(job("mic", 5.0));
        queue.push(job("system", 6.0));
        queue.close();
        assert_eq!(worker.join().unwrap(), 2);
    }

    #[test]
    fn abort_drops_the_rest() {
        let queue = PhraseQueue::default();
        queue.push(job("mic", 0.0));
        queue.push(job("mic", 1.0));
        queue.abort();
        assert_eq!(queue.len(), 0);
        assert!(collect(&queue, None).0.is_empty());
    }
}

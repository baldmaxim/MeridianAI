//! Meeting audio on disk: raw s16le 16 kHz mono, a new piece every minute.
//!
//! Raw PCM has no header, so a crash can only lose the unflushed tail and
//! never corrupts what was written. Layout:
//! `meetings/<meeting_uuid>/audio/<channel>-<NNNN>.pcm`.

use anyhow::{bail, Context, Result};
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime};

pub const SAMPLE_RATE: u32 = 16_000;
/// One file per this many seconds of audio.
pub const PCM_PIECE_SECONDS: usize = 60;
/// Buffered audio reaches the OS at least this often.
pub const FLUSH_INTERVAL: Duration = Duration::from_secs(1);
/// The current piece is forced to the disk (`fsync`) at least this often, so a
/// power cut or a sleep that never wakes loses seconds, not minutes.
pub const SYNC_INTERVAL: Duration = Duration::from_secs(5);

/// Size of the header `hound` writes for 16-bit mono PCM.
const WAV_HEADER_BYTES: u64 = 44;
const WRITE_BUFFER_BYTES: usize = 64 * 1024;

pub fn meeting_dir(meetings_root: &Path, meeting_uuid: &str) -> PathBuf {
    meetings_root.join(meeting_uuid)
}

pub fn audio_dir(meetings_root: &Path, meeting_uuid: &str) -> PathBuf {
    meeting_dir(meetings_root, meeting_uuid).join("audio")
}

fn piece_name(channel: &str, index: u32) -> String {
    format!("{channel}-{index:04}.pcm")
}

/// The pieces of `channel` that exist, ordered by index.
pub fn list_pieces(audio_dir: &Path, channel: &str) -> Vec<(u32, PathBuf)> {
    let prefix = format!("{channel}-");
    let Ok(entries) = fs::read_dir(audio_dir) else {
        return Vec::new();
    };
    let mut pieces: Vec<(u32, PathBuf)> = entries
        .flatten()
        .filter_map(|entry| {
            let name = entry.file_name().to_string_lossy().into_owned();
            let index = name
                .strip_prefix(&prefix)?
                .strip_suffix(".pcm")?
                .parse::<u32>()
                .ok()?;
            Some((index, entry.path()))
        })
        .collect();
    pieces.sort_by_key(|(index, _)| *index);
    pieces
}

/// Size of the WAV `export_channel_wav` would write, from the piece sizes alone.
pub fn channel_wav_size(audio_dir: &Path, channel: &str) -> u64 {
    let pcm: u64 = list_pieces(audio_dir, channel)
        .iter()
        .filter_map(|(_, path)| fs::metadata(path).ok())
        .map(|meta| meta.len() / 2 * 2)
        .sum();
    pcm + WAV_HEADER_BYTES
}

/// Samples recorded for `channel`, from the file sizes alone.
pub fn channel_samples(audio_dir: &Path, channel: &str) -> u64 {
    list_pieces(audio_dir, channel)
        .iter()
        .filter_map(|(_, path)| fs::metadata(path).ok())
        .map(|meta| meta.len() / 2)
        .sum()
}

/// Seconds of audio recorded for `channel`, from the file sizes alone.
pub fn channel_duration_seconds(audio_dir: &Path, channel: &str) -> f64 {
    channel_samples(audio_dir, channel) as f64 / f64::from(SAMPLE_RATE)
}

/// When any audio file of the meeting was last written.
pub fn last_audio_write(audio_dir: &Path) -> Option<SystemTime> {
    fs::read_dir(audio_dir)
        .ok()?
        .flatten()
        .filter_map(|entry| entry.metadata().ok()?.modified().ok())
        .max()
}

/// What the sync thread of a writer is asked to do.
enum SyncJob {
    /// `fsync` this handle (a duplicate of a piece's file).
    File(File),
    /// `fsync` the folder, so a new piece's name survives a power cut.
    Dir(PathBuf),
}

/// Forces the audio to the disk off the capture thread: `fsync` can take tens
/// of milliseconds, and a capture callback must not wait that long.
struct Syncer {
    tx: Option<Sender<SyncJob>>,
    thread: Option<JoinHandle<()>>,
    /// Counts the finished syncs (read by the tests).
    #[cfg_attr(not(test), allow(dead_code))]
    done: Arc<AtomicU64>,
}

impl Syncer {
    fn start() -> Option<Self> {
        let (tx, rx) = mpsc::channel::<SyncJob>();
        let done = Arc::new(AtomicU64::new(0));
        let counter = Arc::clone(&done);
        let thread = std::thread::Builder::new()
            .name("meeting-fsync".into())
            .spawn(move || {
                for job in rx {
                    let result = match job {
                        SyncJob::File(file) => file.sync_data(),
                        SyncJob::Dir(dir) => sync_dir(&dir),
                    };
                    match result {
                        Ok(()) => {
                            counter.fetch_add(1, Ordering::Relaxed);
                        }
                        Err(e) => log::warn!("Syncing meeting audio to disk failed: {e}"),
                    }
                }
            })
            .ok()?;
        Some(Self {
            tx: Some(tx),
            thread: Some(thread),
            done,
        })
    }

    fn request(&self, job: SyncJob) {
        if let Some(tx) = &self.tx {
            let _ = tx.send(job);
        }
    }

    /// Waits until everything asked for is on the disk.
    fn finish(mut self) {
        // Closing the channel ends the thread once it has done the queue.
        self.tx.take();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

#[cfg(unix)]
fn sync_dir(dir: &Path) -> std::io::Result<()> {
    File::open(dir)?.sync_all()
}

/// Windows cannot `fsync` a folder; NTFS keeps the names in its journal.
#[cfg(not(unix))]
fn sync_dir(_dir: &Path) -> std::io::Result<()> {
    Ok(())
}

/// Appends 16 kHz mono samples to numbered pieces of one channel. A resumed
/// meeting continues after the last existing piece.
pub struct PcmWriter {
    dir: PathBuf,
    channel: String,
    next_index: u32,
    samples_per_piece: usize,
    current: Option<BufWriter<File>>,
    in_piece: usize,
    last_flush: Instant,
    last_sync: Instant,
    sync_interval: Duration,
    syncer: Option<Syncer>,
}

impl PcmWriter {
    pub fn new(dir: &Path, channel: &str, samples_per_piece: usize) -> Result<Self> {
        if samples_per_piece == 0 {
            bail!("piece length must be non-zero");
        }
        fs::create_dir_all(dir).with_context(|| format!("cannot create {}", dir.display()))?;
        let next_index = list_pieces(dir, channel)
            .last()
            .map_or(0, |(index, _)| index + 1);
        Ok(Self {
            dir: dir.to_path_buf(),
            channel: channel.to_string(),
            next_index,
            samples_per_piece,
            current: None,
            in_piece: 0,
            last_flush: Instant::now(),
            last_sync: Instant::now(),
            sync_interval: SYNC_INTERVAL,
            syncer: Syncer::start(),
        })
    }

    /// How many `fsync`s the background thread has completed (for tests).
    #[cfg(test)]
    fn syncs_done(&self) -> u64 {
        self.syncer
            .as_ref()
            .map_or(0, |s| s.done.load(Ordering::Relaxed))
    }

    fn open_next(&mut self) -> std::io::Result<()> {
        let path = self.dir.join(piece_name(&self.channel, self.next_index));
        let file = File::create(path)?;
        self.current = Some(BufWriter::with_capacity(WRITE_BUFFER_BYTES, file));
        self.next_index += 1;
        self.in_piece = 0;
        // The new name goes to the disk with the next sync of the folder.
        if let Some(syncer) = &self.syncer {
            syncer.request(SyncJob::Dir(self.dir.clone()));
        }
        Ok(())
    }

    /// Asks the background thread to `fsync` the current piece (already flushed
    /// to the OS). Never waits.
    fn request_sync(&mut self) {
        self.last_sync = Instant::now();
        let (Some(syncer), Some(writer)) = (&self.syncer, &self.current) else {
            return;
        };
        match writer.get_ref().try_clone() {
            Ok(file) => syncer.request(SyncJob::File(file)),
            Err(e) => log::warn!("Cannot duplicate a meeting audio handle: {e}"),
        }
    }

    pub fn write(&mut self, mut samples: &[i16]) -> std::io::Result<()> {
        while !samples.is_empty() {
            if self.current.is_none() || self.in_piece >= self.samples_per_piece {
                // Finish the full piece before starting the next one, and make
                // sure it is on the disk for good.
                self.flush()?;
                self.request_sync();
                self.open_next()?;
            }
            let room = self.samples_per_piece - self.in_piece;
            let (now, rest) = samples.split_at(samples.len().min(room));
            let writer = self.current.as_mut().expect("piece opened above");
            for sample in now {
                writer.write_all(&sample.to_le_bytes())?;
            }
            self.in_piece += now.len();
            samples = rest;
        }
        Ok(())
    }

    pub fn flush(&mut self) -> std::io::Result<()> {
        self.last_flush = Instant::now();
        match self.current.as_mut() {
            Some(writer) => writer.flush(),
            None => Ok(()),
        }
    }

    /// Flushes when [`FLUSH_INTERVAL`] has passed since the last flush, and
    /// asks for an `fsync` when the sync interval has passed.
    pub fn flush_if_due(&mut self) -> std::io::Result<()> {
        if self.last_flush.elapsed() >= FLUSH_INTERVAL {
            self.flush()?;
            if self.last_sync.elapsed() >= self.sync_interval {
                self.request_sync();
            }
        }
        Ok(())
    }

    /// Writes out what is buffered and waits until it is on the disk.
    pub fn finish(mut self) -> std::io::Result<()> {
        let flushed = self.flush();
        // Stop and restart of a capture end here: this one may wait.
        let synced = match self.current.take() {
            Some(writer) => writer
                .into_inner()
                .map_err(std::io::IntoInnerError::into_error)
                .and_then(|file| file.sync_data()),
            None => Ok(()),
        };
        if let Some(syncer) = self.syncer.take() {
            syncer.finish();
        }
        flushed.and(synced)
    }
}

/// Joins the pieces of `channel` into `meetings/<uuid>/<channel>.wav` (16 kHz
/// mono 16-bit) and returns its path. Streams piece by piece, so hours of
/// audio never sit in memory.
pub fn export_channel_wav(
    meetings_root: &Path,
    meeting_uuid: &str,
    channel: &str,
) -> Result<PathBuf> {
    let audio = audio_dir(meetings_root, meeting_uuid);
    let pieces = list_pieces(&audio, channel);
    if pieces.is_empty() {
        bail!("no audio recorded for channel '{channel}'");
    }
    let out_path = meeting_dir(meetings_root, meeting_uuid).join(format!("{channel}.wav"));
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: SAMPLE_RATE,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut wav = hound::WavWriter::create(&out_path, spec)
        .with_context(|| format!("cannot create {}", out_path.display()))?;

    let mut bytes = vec![0u8; 32 * 1024];
    for (_, path) in &pieces {
        let mut reader = BufReader::new(
            File::open(path).with_context(|| format!("cannot open {}", path.display()))?,
        );
        // A torn last byte of a piece (crash mid-sample) is dropped.
        let mut carry: Option<u8> = None;
        loop {
            let read = reader.read(&mut bytes)?;
            if read == 0 {
                break;
            }
            for &byte in &bytes[..read] {
                match carry.take() {
                    Some(low) => wav.write_sample(i16::from_le_bytes([low, byte]))?,
                    None => carry = Some(byte),
                }
            }
        }
    }
    wav.finalize()?;
    Ok(out_path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn ramp(n: usize) -> Vec<i16> {
        (0..n).map(|i| (i % 30_000) as i16 - 100).collect()
    }

    #[test]
    fn rotates_pieces_and_counts_duration_by_size() {
        let dir = tempdir().unwrap();
        let audio = dir.path().join("audio");
        // 1 second pieces of 16 000 samples, 2.5 seconds written.
        let mut writer = PcmWriter::new(&audio, "mic", 16_000).unwrap();
        let samples = ramp(40_000);
        for chunk in samples.chunks(512) {
            writer.write(chunk).unwrap();
        }
        writer.finish().unwrap();

        let pieces = list_pieces(&audio, "mic");
        assert_eq!(pieces.len(), 3);
        assert_eq!(pieces[0].1.file_name().unwrap(), "mic-0000.pcm");
        assert_eq!(fs::metadata(&pieces[0].1).unwrap().len(), 32_000);
        assert_eq!(fs::metadata(&pieces[2].1).unwrap().len(), 16_000);
        assert!((channel_duration_seconds(&audio, "mic") - 2.5).abs() < 1e-9);
        assert_eq!(channel_duration_seconds(&audio, "system"), 0.0);
    }

    #[test]
    fn resumed_writer_continues_numbering() {
        let dir = tempdir().unwrap();
        let audio = dir.path().join("audio");
        let mut first = PcmWriter::new(&audio, "mic", 1000).unwrap();
        first.write(&ramp(1500)).unwrap();
        first.finish().unwrap();

        let mut second = PcmWriter::new(&audio, "mic", 1000).unwrap();
        second.write(&ramp(10)).unwrap();
        second.finish().unwrap();

        let indexes: Vec<u32> = list_pieces(&audio, "mic").iter().map(|p| p.0).collect();
        assert_eq!(indexes, vec![0, 1, 2]);
        assert_eq!(channel_duration_seconds(&audio, "mic"), 1510.0 / 16_000.0);
    }

    #[test]
    fn data_is_on_disk_after_flush_without_finish() {
        let dir = tempdir().unwrap();
        let audio = dir.path().join("audio");
        let mut writer = PcmWriter::new(&audio, "mic", 16_000).unwrap();
        writer.write(&ramp(800)).unwrap();
        writer.flush().unwrap();
        // Simulates a crash: the writer is never finished.
        assert_eq!(channel_duration_seconds(&audio, "mic"), 800.0 / 16_000.0);
        std::mem::forget(writer);
    }

    #[test]
    fn rotation_and_finish_force_the_audio_to_the_disk() {
        let dir = tempdir().unwrap();
        let audio = dir.path().join("audio");
        let mut writer = PcmWriter::new(&audio, "mic", 1000).unwrap();
        writer.write(&ramp(2500)).unwrap();
        // Two full pieces were closed by the rotation: each asked for an
        // fsync of the file, and the folder for each new name. The thread
        // does them on its own time, so wait for it.
        let deadline = Instant::now() + Duration::from_secs(5);
        while writer.syncs_done() < 5 && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(writer.syncs_done() >= 5, "synced {}", writer.syncs_done());
        writer.finish().unwrap();
        // Nothing was lost on the way, and the pieces are plain PCM.
        assert_eq!(channel_duration_seconds(&audio, "mic"), 2500.0 / 16_000.0);
    }

    #[test]
    fn the_current_piece_is_synced_on_the_interval_without_rotation() {
        let dir = tempdir().unwrap();
        let audio = dir.path().join("audio");
        let mut writer = PcmWriter::new(&audio, "mic", 16_000).unwrap();
        writer.sync_interval = Duration::ZERO;
        writer.write(&ramp(100)).unwrap();
        let before = writer.syncs_done();
        // Make both the flush and the sync due.
        writer.last_flush = Instant::now() - FLUSH_INTERVAL * 2;
        writer.flush_if_due().unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while writer.syncs_done() <= before && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(writer.syncs_done() > before);
        // On disk before the writer is finished (a power cut here keeps it).
        assert_eq!(channel_duration_seconds(&audio, "mic"), 100.0 / 16_000.0);
        writer.finish().unwrap();
    }

    #[test]
    fn exports_wav_with_header_and_length() {
        let root = tempdir().unwrap();
        let audio = audio_dir(root.path(), "m1");
        let mut writer = PcmWriter::new(&audio, "mic", 1000).unwrap();
        let samples = ramp(2500);
        writer.write(&samples).unwrap();
        writer.finish().unwrap();
        // Torn trailing byte of the last piece is ignored.
        let last = list_pieces(&audio, "mic").pop().unwrap().1;
        let mut file = fs::OpenOptions::new().append(true).open(last).unwrap();
        file.write_all(&[0x7f]).unwrap();

        let path = export_channel_wav(root.path(), "m1", "mic").unwrap();
        assert_eq!(path, root.path().join("m1").join("mic.wav"));
        let mut reader = hound::WavReader::open(&path).unwrap();
        let spec = reader.spec();
        assert_eq!(spec.sample_rate, 16_000);
        assert_eq!(spec.channels, 1);
        assert_eq!(spec.bits_per_sample, 16);
        assert_eq!(reader.len() as usize, samples.len());
        let read: Vec<i16> = reader.samples::<i16>().map(Result::unwrap).collect();
        assert_eq!(read, samples);
    }

    #[test]
    fn export_without_audio_is_an_error() {
        let root = tempdir().unwrap();
        assert!(export_channel_wav(root.path(), "none", "mic").is_err());
    }
}

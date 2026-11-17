//! Offline quality harness for local diarization (not a regression test).
//!
//! `DIAR_WAV=in.wav DIAR_OUT=out.json cargo test --release eval_diarization -- --ignored --nocapture`
//! runs the production chain on a 16 kHz mono wav: Silero VAD -> `PhraseSegmenter` ->
//! `VoiceEmbedder` -> `VoiceClusterer`. Writes `DIAR_OUT` (JSON `[{start,end,dur,label,has_emb}]`)
//! and `DIAR_OUT.emb.npy` (float32 `[N, D]`, zero rows where there is no embedding).
//! It also runs the re-clustering of the stop (`recluster`) on the same phrases and writes
//! `DIAR_OUT.recl_auto.json` (the number of speakers by the eigengap) and, with `DIAR_K=n`,
//! `DIAR_OUT.recl_k.json`: the same items with the re-clustered `label`.
//! `eval_recluster` does only that part from an already written `DIAR_OUT` (+ `.emb.npy`).

use std::io::Write;
use std::path::{Path, PathBuf};

use crate::audio_toolkit::SileroVad;

use super::{
    recluster, ReclusterInput, VoiceClusterer, VoiceEmbedder, VoiceMatch, VOICE_MODEL_FILE,
};
use crate::managers::meeting::segmenter::{Phrase, PhraseSegmenter};

const CHUNK: usize = 16_000;

fn read_wav(path: &Path) -> Vec<f32> {
    let mut reader = hound::WavReader::open(path).unwrap();
    let spec = reader.spec();
    assert_eq!((spec.sample_rate, spec.channels), (16_000, 1));
    reader
        .samples::<i16>()
        .map(|s| s.unwrap() as f32 / 32768.0)
        .collect()
}

fn write_npy(path: &Path, rows: &[Vec<f32>], dim: usize) {
    let header = format!(
        "{{'descr': '<f4', 'fortran_order': False, 'shape': ({}, {}), }}",
        rows.len(),
        dim
    );
    let mut head = header.into_bytes();
    // magic(6)+version(2)+len(2) + header + '\n' must be a multiple of 64.
    while (10 + head.len() + 1) % 64 != 0 {
        head.push(b' ');
    }
    head.push(b'\n');
    let mut f = std::io::BufWriter::new(std::fs::File::create(path).unwrap());
    f.write_all(b"\x93NUMPY\x01\x00").unwrap();
    f.write_all(&(head.len() as u16).to_le_bytes()).unwrap();
    f.write_all(&head).unwrap();
    for row in rows {
        for x in row {
            f.write_all(&x.to_le_bytes()).unwrap();
        }
    }
}

/// `out` + `suffix` as a path.
fn sibling(out: &Path, suffix: &str) -> PathBuf {
    let mut name = out.as_os_str().to_owned();
    name.push(suffix);
    PathBuf::from(name)
}

/// Re-clusters the phrases (`items` as written by `eval_diarization`) and writes the relabeled copies.
fn write_reclustered(out: &Path, items: &[serde_json::Value], embs: &[Option<Vec<f32>>]) {
    let inputs: Vec<ReclusterInput> = items
        .iter()
        .zip(embs)
        .enumerate()
        .map(|(i, (item, emb))| ReclusterInput {
            id: i.to_string(),
            start: item["start"].as_f64().unwrap(),
            end: item["end"].as_f64().unwrap(),
            embedding: emb.clone(),
        })
        .collect();
    let k_env = std::env::var("DIAR_K")
        .ok()
        .and_then(|v| v.parse::<usize>().ok());
    for (suffix, k) in [(".recl_auto.json", None), (".recl_k.json", k_env)] {
        if suffix == ".recl_k.json" && k.is_none() {
            continue;
        }
        let started = std::time::Instant::now();
        let result = recluster(&inputs, k);
        let elapsed = started.elapsed().as_millis();
        let voices = result
            .as_ref()
            .map_or(0, |r| r.values().max().map_or(0, |m| m + 1));
        eprintln!(
            "recluster k={k:?}: {} phrases, {voices} voices, {elapsed} ms",
            inputs.len()
        );
        let relabeled: Vec<serde_json::Value> = items
            .iter()
            .enumerate()
            .map(|(i, item)| {
                let mut item = item.clone();
                item["label"] = result
                    .as_ref()
                    .and_then(|r| r.get(&i.to_string()))
                    .map_or(serde_json::Value::Null, |n| {
                        format!("Голос {}", n + 1).into()
                    });
                item
            })
            .collect();
        std::fs::write(
            sibling(out, suffix),
            serde_json::to_string(&relabeled).unwrap(),
        )
        .unwrap();
    }
}

/// Re-clustering only, from the files of an earlier `eval_diarization` run.
#[test]
#[ignore]
fn eval_recluster() {
    let Some(out) = std::env::var_os("DIAR_OUT").map(PathBuf::from) else {
        eprintln!("DIAR_OUT is not set, skipping");
        return;
    };
    let items: Vec<serde_json::Value> =
        serde_json::from_slice(&std::fs::read(&out).unwrap()).unwrap();
    let npy = std::fs::read(sibling(&out, ".emb.npy")).unwrap();
    let head = 10 + u16::from_le_bytes([npy[8], npy[9]]) as usize;
    let floats: Vec<f32> = npy[head..]
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| f32::from_le_bytes(*c))
        .collect();
    let dim = floats.len() / items.len();
    let embs: Vec<Option<Vec<f32>>> = items
        .iter()
        .enumerate()
        .map(|(i, item)| {
            item["has_emb"]
                .as_bool()
                .unwrap()
                .then(|| floats[i * dim..(i + 1) * dim].to_vec())
        })
        .collect();
    write_reclustered(&out, &items, &embs);
}

#[test]
#[ignore]
fn eval_diarization() {
    let (Some(wav), Some(out)) = (
        std::env::var_os("DIAR_WAV").map(PathBuf::from),
        std::env::var_os("DIAR_OUT").map(PathBuf::from),
    ) else {
        eprintln!("DIAR_WAV / DIAR_OUT are not set, skipping");
        return;
    };
    let models = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/models");
    let scorer = SileroVad::new(models.join("silero-vad-v6.2-F32.gguf"), 0.3).unwrap();
    let embedder = VoiceEmbedder::load(&models.join(VOICE_MODEL_FILE)).unwrap();
    let samples = read_wav(&wav);

    let mut segmenter = PhraseSegmenter::new(Box::new(scorer), 0.0);
    let mut phrases: Vec<Phrase> = Vec::new();
    for piece in samples.chunks(CHUNK) {
        phrases.extend(segmenter.push(piece));
    }
    phrases.extend(segmenter.finish());
    eprintln!("phrases: {}", phrases.len());

    let mut clusterer = VoiceClusterer::new(vec![]);
    let mut dim = 0;
    let mut embs: Vec<Option<Vec<f32>>> = Vec::new();
    let mut items = Vec::new();
    for p in &phrases {
        let dur = (p.end - p.start) as f32;
        let emb = embedder.embed(&p.samples);
        let label = emb.as_ref().and_then(|e| {
            dim = e.len();
            clusterer.assign(e, dur).map(|m| match m {
                VoiceMatch::New(l) | VoiceMatch::Existing(l) => l,
            })
        });
        items.push(serde_json::json!({
            "start": p.start, "end": p.end, "dur": dur,
            "label": label, "has_emb": emb.is_some(),
        }));
        embs.push(emb);
    }
    let rows: Vec<Vec<f32>> = embs
        .iter()
        .map(|e| e.clone().unwrap_or_else(|| vec![0.0; dim]))
        .collect();
    std::fs::write(&out, serde_json::to_string(&items).unwrap()).unwrap();
    write_npy(&sibling(&out, ".emb.npy"), &rows, dim);
    write_reclustered(&out, &items, &embs);
    eprintln!(
        "voices: {}, written {}",
        clusterer.voices.len(),
        out.display()
    );
}

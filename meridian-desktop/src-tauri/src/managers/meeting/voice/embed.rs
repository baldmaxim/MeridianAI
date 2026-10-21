//! Speaker embedding: Kaldi fbank -> mean normalization -> CAM++ (tract) -> L2 vector.

use std::io::Cursor;
use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, Context, Result};
use log::warn;
use tract_onnx::prelude::*;

use super::fbank::{subtract_mean, Fbank, NUM_MEL, SAMPLE_RATE};

/// Shorter audio gives a useless embedding.
const MIN_SECS: f32 = 0.8;
/// Only the beginning of a long phrase is used: enough for a voice, bounded cost.
const MAX_SECS: f32 = 10.0;

/// The CAM++ context-aware layers average-pool the time axis in 100-frame segments
/// (`kernel = stride = 100, ceil_mode = 1, count_include_pad = 1`). For the last, partial
/// segment PyTorch (and tract, onnxruntime >= 1.29) divide by the real length; the
/// onnxruntime 1.28 inside sherpa-onnx divides by 100. The two differ by ~0.98 cosine on
/// the final vectors with equal speaker separation. `true` reproduces sherpa-onnx exactly
/// (reference vectors, thresholds tuned on them); `false` keeps the PyTorch semantics.
const SHERPA_COMPAT_POOLING: bool = true;

type Plan = Arc<TypedRunnableModel>;

/// Rewrites `AveragePool(ceil_mode = 1, no pads, stride = kernel)` into the equivalent of
/// zero-padding the last segment: `ceil_mode = 0, pads_end = kernel - 1`, which divides every
/// window by the full kernel and yields the same number of windows.
fn sherpa_compat_pooling(proto: &mut tract_onnx::pb::ModelProto) {
    let Some(graph) = proto.graph.as_mut() else {
        return;
    };
    for node in graph.node.iter_mut().filter(|n| n.op_type == "AveragePool") {
        let int_of = |name: &str| node.attribute.iter().find(|a| a.name == name).map(|a| a.i);
        let ints_of = |name: &str| {
            node.attribute
                .iter()
                .find(|a| a.name == name)
                .map(|a| a.ints.clone())
        };
        let (kernel, strides) = (ints_of("kernel_shape"), ints_of("strides"));
        let pads = ints_of("pads").unwrap_or_default();
        let compatible = int_of("ceil_mode") == Some(1)
            && int_of("count_include_pad") == Some(1)
            && kernel.as_ref().is_some_and(|k| k.len() == 1)
            && kernel == strides
            && pads.iter().all(|&p| p == 0);
        if !compatible {
            continue;
        }
        let k = kernel.map_or(1, |k| k[0]);
        for attr in node.attribute.iter_mut() {
            match attr.name.as_str() {
                "ceil_mode" => attr.i = 0,
                "pads" => attr.ints = vec![0, k - 1],
                _ => {}
            }
        }
        if !node.attribute.iter().any(|a| a.name == "pads") {
            let mut pads_attr = node.attribute[0].clone();
            pads_attr.name = "pads".into();
            pads_attr.ints = vec![0, k - 1];
            pads_attr.i = 0;
            pads_attr.r#type = tract_onnx::pb::attribute_proto::AttributeType::Ints as i32;
            node.attribute.push(pads_attr);
        }
    }
}

pub struct VoiceEmbedder {
    fbank: Fbank,
    plan: Plan,
}

impl VoiceEmbedder {
    /// Reads the file into memory and loads the model from bytes (non-ASCII paths are fine).
    pub fn load(model_path: &Path) -> Result<Self> {
        let bytes = std::fs::read(model_path)
            .with_context(|| format!("reading voice model {}", model_path.display()))?;
        let onnx = tract_onnx::onnx();
        let mut proto = onnx
            .proto_model_for_read(&mut Cursor::new(bytes))
            .map_err(|e| anyhow!("parsing voice model: {e}"))?;
        if SHERPA_COMPAT_POOLING {
            sherpa_compat_pooling(&mut proto);
        }
        let model = onnx
            .model_for_proto_model(&proto)
            .map_err(|e| anyhow!("loading voice model: {e}"))?;
        // Input is `[N, T, 80]` fbank with a symbolic time axis.
        let time = model.symbols.sym("T");
        let plan = model
            .with_input_fact(
                0,
                f32::fact([1.to_dim(), time.to_dim(), (NUM_MEL as i64).to_dim()]).into(),
            )
            .and_then(|m| m.into_optimized())
            .and_then(|m| m.into_runnable())
            .map_err(|e| anyhow!("preparing voice model: {e}"))?;
        Ok(Self {
            fbank: Fbank::new(),
            plan,
        })
    }

    /// L2-normalized embedding of the first ten seconds of 16 kHz mono audio;
    /// `None` for audio shorter than 0.8 s or on an inference failure.
    pub fn embed(&self, samples_16k: &[f32]) -> Option<Vec<f32>> {
        if (samples_16k.len() as f32) < MIN_SECS * SAMPLE_RATE as f32 {
            return None;
        }
        let used = samples_16k
            .len()
            .min((MAX_SECS * SAMPLE_RATE as f32) as usize);
        let mut feats = self.fbank.compute(&samples_16k[..used]);
        subtract_mean(&mut feats, NUM_MEL);
        let frames = feats.len() / NUM_MEL;
        match self.run(feats, frames) {
            Ok(v) => Some(v),
            Err(e) => {
                warn!("voice embedding failed: {e}");
                None
            }
        }
    }

    fn run(&self, feats: Vec<f32>, frames: usize) -> TractResult<Vec<f32>> {
        let input = tract_ndarray::Array3::from_shape_vec((1, frames, NUM_MEL), feats)?;
        let out = self.plan.run(tvec!(input.into_tensor().into()))?;
        let mut v: Vec<f32> = out[0]
            .cast_to::<f32>()?
            .into_owned()
            .into_plain_array::<f32>()?
            .iter()
            .cloned()
            .collect();
        let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        if !norm.is_finite() || norm <= f32::EPSILON {
            return Err(anyhow!("degenerate embedding (norm {norm})"));
        }
        v.iter_mut().for_each(|x| *x /= norm);
        Ok(v)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::time::Instant;

    fn cosine(a: &[f32], b: &[f32]) -> f32 {
        let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
        let na = a.iter().map(|x| x * x).sum::<f32>().sqrt();
        let nb = b.iter().map(|x| x * x).sum::<f32>().sqrt();
        dot / (na * nb)
    }

    fn read_wav(path: &Path) -> Vec<f32> {
        let mut reader = hound::WavReader::open(path).unwrap();
        assert_eq!(reader.spec().sample_rate, 16_000);
        reader
            .samples::<i16>()
            .map(|s| s.unwrap() as f32 / 32768.0)
            .collect()
    }

    /// Reference embeddings from the official sherpa-onnx: lines
    /// `<clip>@<full|3s|1s>\t<samples> v0 v1 ...`.
    fn read_reference(path: &Path) -> Vec<(String, usize, Vec<f32>)> {
        std::fs::read_to_string(path)
            .unwrap()
            .lines()
            .map(|l| {
                let (name, rest) = l.split_once('\t').unwrap();
                let mut it = rest.split(' ');
                let n = it.next().unwrap().parse().unwrap();
                (
                    name.to_string(),
                    n,
                    it.map(|x| x.parse().unwrap()).collect(),
                )
            })
            .collect()
    }

    /// Needs the model (`scripts/fetch-voice-model.mjs`) and a directory in
    /// `VOICE_REF_DIR` with the clips `<name>.wav` and `ref_campplus.txt` made by sherpa-onnx.
    #[test]
    #[ignore]
    fn matches_sherpa_reference() {
        let model = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/models")
            .join(super::super::VOICE_MODEL_FILE);
        let Some(dir) = std::env::var_os("VOICE_REF_DIR").map(PathBuf::from) else {
            eprintln!("VOICE_REF_DIR is not set, skipping");
            return;
        };
        if !model.exists() || !dir.join("ref_campplus.txt").exists() {
            eprintln!("model or reference missing, skipping");
            return;
        }
        let embedder = VoiceEmbedder::load(&model).unwrap();
        let mut full = Vec::new();
        for (name, n, reference) in read_reference(&dir.join("ref_campplus.txt")) {
            let (clip, tag) = name.split_once('@').unwrap();
            let samples = read_wav(&dir.join(format!("{clip}.wav")));
            let t = Instant::now();
            let ours = embedder.embed(&samples[..n]).unwrap();
            let cos = cosine(&ours, &reference);
            eprintln!(
                "{name:<24} {:>5.1}s cos={cos:.5} {} ms",
                n as f32 / 16000.0,
                t.elapsed().as_millis()
            );
            assert!(cos >= 0.99, "{name}: cosine {cos}");
            if tag == "full" {
                full.push((clip.to_string(), ours));
            }
        }
        // Same speaker vs different speakers.
        let (mut same, mut diff) = (Vec::new(), Vec::new());
        for i in 0..full.len() {
            for j in i + 1..full.len() {
                let c = cosine(&full[i].1, &full[j].1);
                let same_spk = full[i].0.split('-').next() == full[j].0.split('-').next();
                if same_spk {
                    same.push(c)
                } else {
                    diff.push(c)
                }
            }
        }
        let min = |v: &[f32]| v.iter().cloned().fold(f32::MAX, f32::min);
        let max = |v: &[f32]| v.iter().cloned().fold(f32::MIN, f32::max);
        eprintln!(
            "same: min {:.3} max {:.3}; diff: min {:.3} max {:.3}",
            min(&same),
            max(&same),
            min(&diff),
            max(&diff)
        );
        assert!(min(&same) > max(&diff));
    }

    #[test]
    fn missing_model_is_an_error() {
        assert!(VoiceEmbedder::load(Path::new("/nonexistent/модель.onnx")).is_err());
    }
}

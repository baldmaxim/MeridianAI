//! Kaldi-compatible log-mel filterbank, matching kaldi-native-fbank as sherpa-onnx
//! configures it for 3D-Speaker models: 80 mel bins in 20..7600 Hz, 25 ms povey
//! window, 10 ms shift, preemphasis 0.97, DC offset removed, no dither,
//! `snip_edges = false` (edges are reflected), power spectrum, natural log.
//! Samples are floats in [-1, 1] (model metadata `normalize_samples = 1`).

use std::sync::Arc;

use rustfft::num_complex::Complex32;
use rustfft::{Fft, FftPlanner};

pub const SAMPLE_RATE: usize = 16_000;
pub const NUM_MEL: usize = 80;

const FRAME_LEN: usize = 400; // 25 ms
const FRAME_SHIFT: usize = 160; // 10 ms
const FFT_SIZE: usize = 512; // next power of two >= FRAME_LEN
const LOW_FREQ: f32 = 20.0;
const HIGH_FREQ: f32 = 7600.0; // Nyquist - 400
const PREEMPH: f32 = 0.97;

fn mel_scale(freq: f32) -> f32 {
    1127.0 * (1.0 + freq / 700.0).ln()
}

/// One mel filter: weights for FFT bins `first .. first + weights.len()`.
struct MelBin {
    first: usize,
    weights: Vec<f32>,
}

pub struct Fbank {
    window: Vec<f32>,
    mel: Vec<MelBin>,
    fft: Arc<dyn Fft<f32>>,
}

impl Fbank {
    pub fn new() -> Self {
        let a = std::f64::consts::TAU / (FRAME_LEN as f64 - 1.0);
        let window = (0..FRAME_LEN)
            .map(|i| (0.5 - 0.5 * (a * i as f64).cos()).powf(0.85) as f32)
            .collect();
        Self {
            window,
            mel: build_mel_bins(),
            fft: FftPlanner::new().plan_fft_forward(FFT_SIZE),
        }
    }

    /// Number of frames for `num_samples` (kaldi, `snip_edges = false`).
    pub fn num_frames(num_samples: usize) -> usize {
        (num_samples + FRAME_SHIFT / 2) / FRAME_SHIFT
    }

    /// Row-major `frames x NUM_MEL` log-mel features (no mean normalization).
    pub fn compute(&self, samples: &[f32]) -> Vec<f32> {
        let frames = Self::num_frames(samples.len());
        let mut out = Vec::with_capacity(frames * NUM_MEL);
        if samples.is_empty() {
            return out;
        }
        let mut frame = [0f32; FRAME_LEN];
        let mut buf = vec![Complex32::new(0.0, 0.0); FFT_SIZE];
        let mut scratch = vec![Complex32::new(0.0, 0.0); self.fft.get_inplace_scratch_len()];
        let mut power = [0f32; FFT_SIZE / 2];
        let n = samples.len() as i64;
        for f in 0..frames {
            // Frame start for snip_edges = false: centered on f * shift + shift / 2.
            let start = (FRAME_SHIFT * f + FRAME_SHIFT / 2) as i64 - (FRAME_LEN / 2) as i64;
            for (s, slot) in frame.iter_mut().enumerate() {
                *slot = samples[reflect(start + s as i64, n)];
            }
            let mean = frame.iter().sum::<f32>() / FRAME_LEN as f32;
            for v in frame.iter_mut() {
                *v -= mean;
            }
            for i in (1..FRAME_LEN).rev() {
                frame[i] -= PREEMPH * frame[i - 1];
            }
            frame[0] -= PREEMPH * frame[0];
            for (i, c) in buf.iter_mut().enumerate() {
                *c = Complex32::new(
                    if i < FRAME_LEN {
                        frame[i] * self.window[i]
                    } else {
                        0.0
                    },
                    0.0,
                );
            }
            self.fft.process_with_scratch(&mut buf, &mut scratch);
            for (p, c) in power.iter_mut().zip(buf.iter()) {
                *p = c.norm_sqr();
            }
            for bin in &self.mel {
                let e: f32 = bin
                    .weights
                    .iter()
                    .zip(&power[bin.first..])
                    .map(|(w, p)| w * p)
                    .sum();
                out.push(e.max(f32::EPSILON).ln());
            }
        }
        out
    }
}

/// Mirror an out-of-range index back into `0..n` (kaldi: -1 -> 0, n -> n - 1).
fn reflect(mut i: i64, n: i64) -> usize {
    while i < 0 || i >= n {
        i = if i < 0 { -i - 1 } else { 2 * n - 1 - i };
    }
    i as usize
}

fn build_mel_bins() -> Vec<MelBin> {
    let num_fft_bins = FFT_SIZE / 2;
    let bin_width = SAMPLE_RATE as f32 / FFT_SIZE as f32;
    let mel_low = mel_scale(LOW_FREQ);
    let mel_high = mel_scale(HIGH_FREQ);
    let delta = (mel_high - mel_low) / (NUM_MEL + 1) as f32;
    (0..NUM_MEL)
        .map(|b| {
            let left = mel_low + b as f32 * delta;
            let center = mel_low + (b + 1) as f32 * delta;
            let right = mel_low + (b + 2) as f32 * delta;
            let mut first = None;
            let mut weights = Vec::new();
            for i in 0..num_fft_bins {
                let mel = mel_scale(bin_width * i as f32);
                if mel > left && mel < right {
                    first.get_or_insert(i);
                    weights.push(if mel <= center {
                        (mel - left) / (center - left)
                    } else {
                        (right - mel) / (right - center)
                    });
                }
            }
            MelBin {
                first: first.unwrap_or(0),
                weights,
            }
        })
        .collect()
}

/// Subtract the per-dimension mean over time (`feature_normalize_type = global-mean`).
pub fn subtract_mean(feats: &mut [f32], dim: usize) {
    let frames = feats.len() / dim;
    if frames == 0 {
        return;
    }
    for d in 0..dim {
        let mean = (0..frames).map(|t| feats[t * dim + d]).sum::<f32>() / frames as f32;
        for t in 0..frames {
            feats[t * dim + d] -= mean;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tone(secs: f32, freq: f32) -> Vec<f32> {
        (0..(secs * SAMPLE_RATE as f32) as usize)
            .map(|i| 0.3 * (std::f32::consts::TAU * freq * i as f32 / SAMPLE_RATE as f32).sin())
            .collect()
    }

    #[test]
    fn frame_count_matches_kaldi_without_snip_edges() {
        assert_eq!(Fbank::num_frames(16_000), 100);
        assert_eq!(Fbank::num_frames(0), 0);
        assert_eq!(Fbank::num_frames(400), 3);
    }

    #[test]
    fn shapes_and_values_are_finite() {
        let fb = Fbank::new();
        let samples = tone(1.0, 440.0);
        let feats = fb.compute(&samples);
        assert_eq!(feats.len(), 100 * NUM_MEL);
        assert!(feats.iter().all(|v| v.is_finite()));
        // Silence stays finite too (log of epsilon, not -inf).
        let silent = fb.compute(&vec![0.0; 8_000]);
        assert_eq!(silent.len(), 50 * NUM_MEL);
        assert!(silent.iter().all(|v| v.is_finite()));
        assert!(fb.compute(&[]).is_empty());
    }

    #[test]
    fn tone_energy_lands_in_matching_mel_bin() {
        let fb = Fbank::new();
        let low = fb.compute(&tone(0.5, 300.0));
        let high = fb.compute(&tone(0.5, 3000.0));
        let argmax = |f: &[f32]| {
            let row = &f[20 * NUM_MEL..21 * NUM_MEL];
            row.iter()
                .enumerate()
                .max_by(|a, b| a.1.total_cmp(b.1))
                .unwrap()
                .0
        };
        assert!(argmax(&low) < argmax(&high));
    }

    #[test]
    fn mean_subtraction_zeroes_each_dimension() {
        let fb = Fbank::new();
        let mut feats = fb.compute(&tone(1.0, 700.0));
        subtract_mean(&mut feats, NUM_MEL);
        for d in 0..NUM_MEL {
            let mean = (0..100).map(|t| feats[t * NUM_MEL + d]).sum::<f32>() / 100.0;
            assert!(mean.abs() < 1e-3, "dim {d}: {mean}");
        }
    }
}

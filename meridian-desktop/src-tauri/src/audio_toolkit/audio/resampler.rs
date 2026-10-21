//! Streaming mono resampler for capture paths that bypass `handy-recorder`
//! (WASAPI loopback of a playback device), whose own resampler is private.
//!
//! Windowed-sinc polyphase: the rates are reduced by their gcd, so every
//! output sample has one of `out/gcd` exact phases (3 for 48 kHz -> 16 kHz,
//! 160 for 44.1 kHz -> 16 kHz) and the kernel weights are tabulated once.

use anyhow::{bail, Result};
use std::f64::consts::PI;

/// Zero crossings of the kernel on each side, at the output rate.
const KERNEL_LOBES: f64 = 8.0;
/// Passband edge as a fraction of the output Nyquist rate.
const CUTOFF_MARGIN: f64 = 0.95;

pub struct StreamResampler {
    /// Reduced input rate: input samples advanced per `phases` output samples.
    step: u64,
    /// Reduced output rate: number of distinct fractional positions.
    phases: u64,
    /// Kernel taps on each side of the output position.
    half: usize,
    /// `table[phase][tap]`, each row summing to 1.
    table: Vec<Vec<f32>>,
    /// Input from absolute index `buf_start` on.
    buf: Vec<f32>,
    buf_start: i64,
    next_out: u64,
}

fn gcd(a: u64, b: u64) -> u64 {
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

fn sinc(x: f64) -> f64 {
    if x.abs() < 1e-9 {
        1.0
    } else {
        (PI * x).sin() / (PI * x)
    }
}

impl StreamResampler {
    pub fn new(in_hz: u32, out_hz: u32) -> Result<Self> {
        if in_hz == 0 || out_hz == 0 {
            bail!("sample rates must be non-zero (got {in_hz} -> {out_hz})");
        }
        let g = gcd(u64::from(in_hz), u64::from(out_hz));
        let step = u64::from(in_hz) / g;
        let phases = u64::from(out_hz) / g;

        // Kernel width is set at the lower of the two rates, in input samples.
        let ratio = f64::from(in_hz) / f64::from(out_hz);
        let cutoff = (1.0 / ratio).min(1.0) * CUTOFF_MARGIN;
        let half = (KERNEL_LOBES * ratio.max(1.0)).ceil() as usize;

        let table = (0..phases)
            .map(|phase| {
                let frac = phase as f64 / phases as f64;
                let mut row: Vec<f64> = (0..2 * half)
                    .map(|tap| {
                        let x = tap as f64 - half as f64 + 1.0 - frac;
                        let window = 0.5 * (1.0 + (PI * x / half as f64).cos());
                        cutoff * sinc(cutoff * x) * window
                    })
                    .collect();
                let sum: f64 = row.iter().sum();
                row.iter_mut().for_each(|w| *w /= sum);
                row.into_iter().map(|w| w as f32).collect()
            })
            .collect();

        Ok(Self {
            step,
            phases,
            half,
            table,
            // Indices before 0 are silence, so the first outputs have a full kernel.
            buf: vec![0.0; half - 1],
            buf_start: 1 - half as i64,
            next_out: 0,
        })
    }

    /// Feeds mono input; appends the output samples it completes to `out`.
    pub fn push(&mut self, input: &[f32], out: &mut Vec<f32>) {
        self.buf.extend_from_slice(input);
        let width = 2 * self.half;
        loop {
            let pos = self.next_out * self.step;
            let q = (pos / self.phases) as i64;
            let phase = (pos % self.phases) as usize;
            if q + self.half as i64 >= self.buf_start + self.buf.len() as i64 {
                break;
            }
            let from = (q - self.half as i64 + 1 - self.buf_start) as usize;
            let acc: f32 = self.table[phase]
                .iter()
                .zip(&self.buf[from..from + width])
                .map(|(w, x)| w * x)
                .sum();
            out.push(acc);
            self.next_out += 1;
        }

        let keep_from = (self.next_out * self.step / self.phases) as i64 - self.half as i64 + 1;
        if keep_from > self.buf_start {
            let drop = ((keep_from - self.buf_start) as usize).min(self.buf.len());
            self.buf.drain(..drop);
            self.buf_start += drop as i64;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sine(hz: f64, rate: f64, seconds: f64, amp: f64) -> Vec<f32> {
        (0..(rate * seconds) as usize)
            .map(|i| (amp * (2.0 * PI * hz * i as f64 / rate).sin()) as f32)
            .collect()
    }

    fn run(in_hz: u32, input: &[f32]) -> Vec<f32> {
        let mut r = StreamResampler::new(in_hz, 16_000).unwrap();
        let mut out = Vec::new();
        r.push(input, &mut out);
        out
    }

    #[test]
    fn keeps_in_band_tone_amplitude_and_phase() {
        let out = run(48_000, &sine(1000.0, 48_000.0, 1.0, 0.5));
        assert!((15_980..=16_000).contains(&out.len()), "len {}", out.len());
        // No delay: compare against the ideal tone away from the edges.
        let worst = (200..out.len() - 200)
            .map(|i| {
                let ideal = 0.5 * (2.0 * PI * 1000.0 * i as f64 / 16_000.0).sin();
                (out[i] as f64 - ideal).abs()
            })
            .fold(0.0, f64::max);
        assert!(worst < 0.01, "worst error {worst}");
    }

    #[test]
    fn handles_non_integer_ratio() {
        let out = run(44_100, &sine(440.0, 44_100.0, 2.0, 0.5));
        let expected = 32_000usize;
        assert!(out.len().abs_diff(expected) <= 40, "len {}", out.len());
        let peak = out[1000..out.len() - 1000]
            .iter()
            .fold(0.0f32, |m, v| m.max(v.abs()));
        assert!((peak - 0.5).abs() < 0.01, "peak {peak}");
    }

    #[test]
    fn attenuates_tone_above_output_nyquist() {
        let out = run(48_000, &sine(12_000.0, 48_000.0, 1.0, 0.5));
        let peak = out[200..out.len() - 200]
            .iter()
            .fold(0.0f32, |m, v| m.max(v.abs()));
        assert!(peak < 0.02, "alias peak {peak}");
    }

    #[test]
    fn chunked_push_equals_whole_push() {
        let input = sine(700.0, 44_100.0, 1.0, 0.4);
        let whole = run(44_100, &input);
        let mut r = StreamResampler::new(44_100, 16_000).unwrap();
        let mut pieces = Vec::new();
        for chunk in input.chunks(1013) {
            r.push(chunk, &mut pieces);
        }
        assert_eq!(whole, pieces);
    }

    #[test]
    fn rejects_zero_rate() {
        assert!(StreamResampler::new(0, 16_000).is_err());
        assert!(StreamResampler::new(48_000, 0).is_err());
    }
}

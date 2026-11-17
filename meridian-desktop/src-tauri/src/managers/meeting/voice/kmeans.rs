//! Weighted k-means (k-means++ start, several restarts) on a tiny seeded
//! generator, so that a re-clustering gives the same voices every time.

/// xorshift64*: enough for sampling start points, no `rand` needed.
pub(super) struct XorShift(u64);

impl XorShift {
    pub(super) fn new(seed: u64) -> Self {
        // Zero is the one state xorshift cannot leave.
        Self(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1)
    }

    fn next_u64(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    /// Uniform in `[0, 1)`.
    pub(super) fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }
}

const MAX_ITERATIONS: usize = 60;

fn dist2(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| (x - y) * (x - y)).sum()
}

/// An index drawn with the probability proportional to its weight.
fn sample(weights: &[f64], rng: &mut XorShift) -> usize {
    let total: f64 = weights.iter().sum();
    if total <= 0.0 {
        return (rng.next_f64() * weights.len() as f64) as usize % weights.len();
    }
    let mut left = rng.next_f64() * total;
    for (i, w) in weights.iter().enumerate() {
        left -= w;
        if left < 0.0 {
            return i;
        }
    }
    weights.len() - 1
}

fn nearest(point: &[f64], centers: &[Vec<f64>]) -> (usize, f64) {
    let mut best = (0, f64::INFINITY);
    for (j, c) in centers.iter().enumerate() {
        let d = dist2(point, c);
        if d < best.1 {
            best = (j, d);
        }
    }
    best
}

/// Labels `0..k` for `points`; `weights` (durations) weigh both the start and
/// the centers. The restart with the least inertia wins.
pub(super) fn kmeans(
    points: &[Vec<f64>],
    weights: &[f64],
    k: usize,
    restarts: usize,
    rng: &mut XorShift,
) -> Vec<usize> {
    let n = points.len();
    let dim = points.first().map_or(0, Vec::len);
    let mut best: Option<(f64, Vec<usize>)> = None;
    for _ in 0..restarts.max(1) {
        let mut centers = vec![points[sample(weights, rng)].clone()];
        while centers.len() < k {
            let spread: Vec<f64> = points
                .iter()
                .zip(weights)
                .map(|(p, w)| nearest(p, &centers).1 * w)
                .collect();
            centers.push(points[sample(&spread, rng)].clone());
        }
        let mut labels = vec![usize::MAX; n];
        for _ in 0..MAX_ITERATIONS {
            let next: Vec<usize> = points.iter().map(|p| nearest(p, &centers).0).collect();
            if next == labels {
                break;
            }
            labels = next;
            for (j, center) in centers.iter_mut().enumerate() {
                let mut sum = vec![0.0; dim];
                let mut mass = 0.0;
                for i in (0..n).filter(|&i| labels[i] == j) {
                    mass += weights[i];
                    sum.iter_mut()
                        .zip(&points[i])
                        .for_each(|(s, x)| *s += x * weights[i]);
                }
                // An empty cluster keeps its old center.
                if mass > 0.0 {
                    *center = sum.into_iter().map(|s| s / mass).collect();
                }
            }
        }
        let inertia: f64 = points
            .iter()
            .zip(weights)
            .zip(&labels)
            .map(|((p, w), l)| w * dist2(p, &centers[*l]))
            .sum();
        if best.as_ref().is_none_or(|(b, _)| inertia < *b) {
            best = Some((inertia, labels));
        }
    }
    best.map(|(_, labels)| labels).unwrap_or_default()
}

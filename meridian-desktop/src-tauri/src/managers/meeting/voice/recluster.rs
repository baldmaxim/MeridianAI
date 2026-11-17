//! Re-clustering of all phrases of a meeting at the stop. The online clusterer
//! sees phrases one by one and splits one speaker into many voices; with every
//! embedding at hand, spectral clustering (see `spectral.rs`) tells the real
//! speakers apart much better.
//!
//! Pure: embeddings in, a voice number per phrase out. The database side is in
//! `db_recluster.rs`.

use std::collections::HashMap;

use super::spectral::{spectral_labels, MAX_K};

/// Phrases shorter than this are too noisy to build the clusters from.
const WORKING_MIN_SECS: f64 = 1.5;
/// Fewer working phrases than this: there is nothing to re-cluster, the online voices stay.
const MIN_WORKING_PHRASES: usize = 20;
/// A phrase shorter than this takes the voice of the nearest phrase in time.
const FILL_BELOW_SECS: f64 = 1.0;
/// A cluster with a smaller share of the speech time joins the nearest one.
const MIN_CLUSTER_SHARE: f64 = 0.02;

/// A phrase of the meeting.
#[derive(Clone, Debug)]
pub struct ReclusterInput {
    pub id: String,
    pub start: f64,
    pub end: f64,
    /// `None`: no embedding (too short, an old meeting).
    pub embedding: Option<Vec<f32>>,
}

fn l2(v: &mut [f64]) {
    let norm = v.iter().map(|x| x * x).sum::<f64>().sqrt();
    if norm > 1e-9 {
        v.iter_mut().for_each(|x| *x /= norm);
    }
}

fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

/// Unit vector of the weighted sum of `rows`.
fn centroid(rows: impl Iterator<Item = (f64, Vec<f64>)>, dim: usize) -> Vec<f64> {
    let mut sum = vec![0.0; dim];
    for (w, row) in rows {
        sum.iter_mut().zip(&row).for_each(|(s, x)| *s += w * x);
    }
    l2(&mut sum);
    sum
}

/// Moves the clusters with under `MIN_CLUSTER_SHARE` of the labelled speech
/// time into the nearest big one (by cosine of the weighted centroids).
fn merge_small(labels: &mut [Option<usize>], x: &[Option<Vec<f64>>], dur: &[f64]) {
    loop {
        let mut share: HashMap<usize, f64> = HashMap::new();
        for (l, d) in labels.iter().zip(dur) {
            if let Some(l) = l {
                *share.entry(*l).or_default() += d;
            }
        }
        let total: f64 = share.values().sum();
        let mut ids: Vec<usize> = share.keys().copied().collect();
        ids.sort_unstable();
        let small: Vec<usize> = ids
            .iter()
            .copied()
            .filter(|l| share[l] / total < MIN_CLUSTER_SHARE)
            .collect();
        if ids.len() < 2 || small.is_empty() {
            return;
        }
        let mut big: Vec<usize> = ids.iter().copied().filter(|l| !small.contains(l)).collect();
        if big.is_empty() {
            let top = ids
                .iter()
                .copied()
                .max_by(|a, b| share[a].total_cmp(&share[b]));
            big.extend(top);
        }
        let dim = x.iter().flatten().next().map_or(0, Vec::len);
        let center = |l: usize| {
            centroid(
                (0..labels.len())
                    .filter(|&i| labels[i] == Some(l))
                    .filter_map(|i| x[i].clone().map(|row| (dur[i], row))),
                dim,
            )
        };
        let big_centers: Vec<(usize, Vec<f64>)> = big.iter().map(|&b| (b, center(b))).collect();
        let moves: Vec<(usize, usize)> = small
            .iter()
            .filter(|l| !big.contains(l))
            .map(|&l| {
                let c = center(l);
                let target = big_centers
                    .iter()
                    .max_by(|a, b| dot(&c, &a.1).total_cmp(&dot(&c, &b.1)))
                    .map_or(l, |b| b.0);
                (l, target)
            })
            .collect();
        if moves.is_empty() {
            return;
        }
        for label in labels.iter_mut().flatten() {
            if let Some((_, to)) = moves.iter().find(|(from, _)| from == label) {
                *label = *to;
            }
        }
    }
}

/// The voice number (from 0, by the first phrase in time) of every phrase of
/// the meeting. `k`: the number of speakers if known (2..=10), else it comes
/// from the eigengap. `None`: too few long phrases with embeddings, keep the
/// online voices.
pub fn recluster(phrases: &[ReclusterInput], k: Option<usize>) -> Option<HashMap<String, usize>> {
    let mut order: Vec<usize> = (0..phrases.len()).collect();
    order.sort_by(|&a, &b| {
        (phrases[a].start, phrases[a].end)
            .partial_cmp(&(phrases[b].start, phrases[b].end))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let ph: Vec<&ReclusterInput> = order.iter().map(|&i| &phrases[i]).collect();
    let n = ph.len();
    let dur: Vec<f64> = ph.iter().map(|p| (p.end - p.start).max(0.0)).collect();

    // Unit embeddings; the dimension is the first one's, odd rows are dropped.
    let dim = ph.iter().find_map(|p| p.embedding.as_ref().map(Vec::len))?;
    let mut x: Vec<Option<Vec<f64>>> = ph
        .iter()
        .map(|p| {
            let e = p.embedding.as_ref().filter(|e| e.len() == dim)?;
            let mut v: Vec<f64> = e.iter().map(|&a| f64::from(a)).collect();
            l2(&mut v);
            v.iter().any(|a| *a != 0.0).then_some(v)
        })
        .collect();

    // Minus the duration-weighted mean voice (what all phrases share: the
    // room, the microphone), then unit again.
    let weight_sum: f64 = x
        .iter()
        .zip(&dur)
        .filter(|(v, _)| v.is_some())
        .map(|(_, d)| d)
        .sum();
    let mut mean = vec![0.0; dim];
    for (v, d) in x.iter().zip(&dur) {
        let w = if weight_sum > 0.0 {
            *d / weight_sum
        } else {
            0.0
        };
        if let Some(v) = v {
            mean.iter_mut().zip(v).for_each(|(m, a)| *m += w * a);
        }
    }
    for v in x.iter_mut().flatten() {
        v.iter_mut().zip(&mean).for_each(|(a, m)| *a -= m);
        l2(v);
    }

    let work: Vec<usize> = (0..n)
        .filter(|&i| x[i].is_some() && dur[i] >= WORKING_MIN_SECS)
        .collect();
    if work.len() < MIN_WORKING_PHRASES {
        return None;
    }
    let points: Vec<Vec<f64>> = work.iter().filter_map(|&i| x[i].clone()).collect();
    let weights: Vec<f64> = work.iter().map(|&i| dur[i]).collect();
    let (cluster, clusters) = spectral_labels(&points, &weights, k);

    let mut labels: Vec<Option<usize>> = vec![None; n];
    for (&i, &c) in work.iter().zip(&cluster) {
        labels[i] = Some(c);
    }
    // The rest with an embedding: the nearest cluster centroid.
    let centers: Vec<(usize, Vec<f64>)> = (0..clusters)
        .filter(|c| cluster.contains(c))
        .map(|c| {
            let members = work
                .iter()
                .zip(&cluster)
                .filter(|(_, l)| **l == c)
                .filter_map(|(&i, _)| x[i].clone().map(|row| (dur[i], row)));
            (c, centroid(members, dim))
        })
        .collect();
    for i in 0..n {
        if labels[i].is_some() {
            continue;
        }
        if let Some(v) = &x[i] {
            labels[i] = centers
                .iter()
                .max_by(|a, b| dot(v, &a.1).total_cmp(&dot(v, &b.1)))
                .map(|c| c.0);
        }
    }
    merge_small(&mut labels, &x, &dur);

    // Short or embedding-less phrases: the voice of the nearest good phrase in time.
    let good: Vec<usize> = (0..n)
        .filter(|&i| labels[i].is_some() && dur[i] >= FILL_BELOW_SECS)
        .collect();
    let settled = labels.clone();
    for i in (0..n).filter(|&i| dur[i] < FILL_BELOW_SECS || settled[i].is_none()) {
        let at = good.partition_point(|&g| g < i);
        let before = at.checked_sub(1).map(|a| good[a]);
        let after = good.get(at).copied();
        labels[i] = match (before, after) {
            (Some(j), Some(m)) => {
                if ph[i].start - ph[j].end <= ph[m].start - ph[i].end {
                    settled[j]
                } else {
                    settled[m]
                }
            }
            (Some(j), None) => settled[j],
            (None, Some(m)) => settled[m],
            (None, None) => None,
        };
    }

    // Numbered by the first phrase in time.
    let mut number: HashMap<usize, usize> = HashMap::new();
    let mut result = HashMap::new();
    for (i, label) in labels.iter().enumerate() {
        if let Some(l) = label {
            let next = number.len();
            let voice = *number.entry(*l).or_insert(next);
            result.insert(ph[i].id.clone(), voice);
        }
    }
    debug_assert!(number.len() <= MAX_K.max(clusters));
    Some(result)
}

#[cfg(test)]
mod tests {
    use super::super::kmeans::XorShift;
    use super::*;

    const DIM: usize = 192;

    fn gauss(rng: &mut XorShift) -> f64 {
        let (u, v) = (rng.next_f64().max(1e-12), rng.next_f64());
        (-2.0 * u.ln()).sqrt() * (std::f64::consts::TAU * v).cos()
    }

    /// `speakers` random directions; `count` phrases of 2-6 s in random order,
    /// noisy (cosine to the own direction ~0.78). Returns the phrases and the true speaker.
    fn meeting(speakers: usize, count: usize, seed: u64) -> (Vec<ReclusterInput>, Vec<usize>) {
        let mut rng = XorShift::new(seed);
        let centers: Vec<Vec<f64>> = (0..speakers)
            .map(|_| {
                let mut c: Vec<f64> = (0..DIM).map(|_| gauss(&mut rng)).collect();
                l2(&mut c);
                c
            })
            .collect();
        // What every phrase shares (the room).
        let bias: Vec<f64> = (0..DIM)
            .map(|_| gauss(&mut rng) * 0.3 / (DIM as f64).sqrt())
            .collect();
        let (mut phrases, mut truth, mut t) = (Vec::new(), Vec::new(), 0.0);
        for i in 0..count {
            let who = (rng.next_f64() * speakers as f64) as usize % speakers;
            let secs = 2.0 + rng.next_f64() * 4.0;
            let e: Vec<f32> = (0..DIM)
                .map(|d| {
                    (centers[who][d] + bias[d] + 0.8 * gauss(&mut rng) / (DIM as f64).sqrt()) as f32
                })
                .collect();
            phrases.push(ReclusterInput {
                id: format!("p{i}"),
                start: t,
                end: t + secs,
                embedding: Some(e),
            });
            truth.push(who);
            t += secs + 0.5;
        }
        (phrases, truth)
    }

    /// Every cluster holds one speaker, and the other way round.
    fn assert_perfect(phrases: &[ReclusterInput], truth: &[usize], got: &HashMap<String, usize>) {
        let mut map: HashMap<usize, usize> = HashMap::new();
        for (p, t) in phrases.iter().zip(truth) {
            let c = got[&p.id];
            assert_eq!(
                *map.entry(c).or_insert(*t),
                *t,
                "mixed speakers in voice {c}"
            );
        }
        let speakers: std::collections::HashSet<_> = truth.iter().collect();
        assert_eq!(map.len(), speakers.len());
    }

    #[test]
    fn the_number_of_speakers_comes_from_the_eigengap() {
        for speakers in [3, 4] {
            let (phrases, truth) = meeting(speakers, 240, 7 + speakers as u64);
            let got = recluster(&phrases, None).unwrap();
            assert_eq!(got.len(), phrases.len());
            assert_perfect(&phrases, &truth, &got);
        }
    }

    #[test]
    fn a_known_number_of_speakers_is_used() {
        let (phrases, truth) = meeting(3, 200, 11);
        let got = recluster(&phrases, Some(3)).unwrap();
        assert_perfect(&phrases, &truth, &got);
        // Clamped to 2..=10: one speaker named is still two clusters at least.
        let two = recluster(&phrases, Some(1)).unwrap();
        assert_eq!(
            two.values().collect::<std::collections::HashSet<_>>().len(),
            2
        );
    }

    #[test]
    fn voices_are_numbered_by_the_first_appearance() {
        let (phrases, _) = meeting(4, 200, 5);
        let got = recluster(&phrases, None).unwrap();
        assert_eq!(got["p0"], 0);
        let mut seen = 0;
        for p in &phrases {
            let v = got[&p.id];
            assert!(v <= seen, "voice {v} appears before voice {seen}");
            seen = seen.max(v + 1);
        }
    }

    #[test]
    fn few_long_phrases_keep_the_online_voices() {
        let (phrases, _) = meeting(2, 19, 3);
        assert!(recluster(&phrases, None).is_none());
        assert!(recluster(&[], None).is_none());
        // Enough phrases, but without embeddings.
        let bare: Vec<ReclusterInput> = meeting(2, 60, 3)
            .0
            .into_iter()
            .map(|p| ReclusterInput {
                embedding: None,
                ..p
            })
            .collect();
        assert!(recluster(&bare, None).is_none());
    }

    #[test]
    fn short_and_bare_phrases_take_the_voice_of_the_nearest_in_time() {
        let (mut phrases, truth) = meeting(3, 120, 9);
        let first = phrases[10].clone();
        // 0.4 s right after phrase 10, without an embedding.
        phrases.push(ReclusterInput {
            id: "bare".into(),
            start: first.end + 0.01,
            end: first.end + 0.41,
            embedding: None,
        });
        // 0.9 s after the last phrase, with an embedding of another speaker.
        let last = phrases[119].clone();
        let other = truth.iter().position(|t| *t != truth[119]).unwrap();
        phrases.push(ReclusterInput {
            id: "short".into(),
            start: last.end + 0.01,
            end: last.end + 0.91,
            embedding: phrases[other].embedding.clone(),
        });
        let got = recluster(&phrases, None).unwrap();
        assert_eq!(got["bare"], got["p10"]);
        assert_eq!(got["short"], got["p119"]);
    }

    #[test]
    fn the_result_does_not_depend_on_the_order_and_repeats() {
        let (phrases, _) = meeting(3, 150, 21);
        let a = recluster(&phrases, None).unwrap();
        assert_eq!(a, recluster(&phrases, None).unwrap());
        let mut shuffled = phrases.clone();
        shuffled.reverse();
        assert_eq!(a, recluster(&shuffled, None).unwrap());
    }
}

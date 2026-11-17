//! Spectral clustering of unit vectors: a sparse nearest-neighbour graph, the
//! top eigenvectors of its normalized affinity by block subspace iteration,
//! the number of clusters by the eigengap, k-means on the rows.

use super::kmeans::{kmeans, XorShift};

/// Neighbours kept per row: at least this many, or this share of the rows.
const MIN_NEIGHBORS: usize = 8;
const NEIGHBOR_SHARE: f64 = 0.01;
/// Eigenvectors tracked: `MAX_K` + 1, so the gap after the last candidate is seen.
const BLOCK: usize = 11;
pub(super) const MAX_K: usize = 10;
const TOLERANCE: f64 = 1e-6;
const MAX_ITERATIONS: usize = 300;
const KMEANS_RESTARTS: usize = 8;
const SEED: u64 = 0x5EED;

type Columns = Vec<Vec<f64>>;

/// A symmetric matrix by rows: `(column, value)`.
struct Sparse {
    rows: Vec<Vec<(usize, f64)>>,
}

impl Sparse {
    fn mul(&self, columns: &Columns) -> Columns {
        columns
            .iter()
            .map(|q| {
                self.rows
                    .iter()
                    .map(|row| row.iter().map(|&(j, v)| v * q[j]).sum())
                    .collect()
            })
            .collect()
    }
}

fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

/// `D^-1/2 A D^-1/2` of the symmetrized graph that keeps, per row, the `m`
/// largest positive cosines.
fn normalized_affinity(x: &[Vec<f64>], m: usize) -> Sparse {
    let n = x.len();
    let mut sim = vec![0.0; n * n];
    for i in 0..n {
        for j in i + 1..n {
            let s = dot(&x[i], &x[j]);
            sim[i * n + j] = s;
            sim[j * n + i] = s;
        }
    }
    // Both halves of a mutual pair add up to the full value, a one-sided pair gets half.
    let mut triples: Vec<(usize, usize, f64)> = Vec::with_capacity(2 * n * m);
    let mut row: Vec<(f64, usize)> = Vec::with_capacity(n);
    for i in 0..n {
        row.clear();
        row.extend((0..n).filter(|&j| j != i).map(|j| (sim[i * n + j], j)));
        let top = m.min(row.len());
        row.select_nth_unstable_by(top - 1, |a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
        for &(s, j) in row[..top].iter().filter(|(s, _)| *s > 0.0) {
            triples.push((i, j, s / 2.0));
            triples.push((j, i, s / 2.0));
        }
    }
    triples.sort_by_key(|&(i, j, _)| (i, j));
    let mut rows: Vec<Vec<(usize, f64)>> = vec![Vec::new(); n];
    for (i, j, v) in triples {
        match rows[i].last_mut() {
            Some(last) if last.0 == j => last.1 += v,
            _ => rows[i].push((j, v)),
        }
    }
    let scale: Vec<f64> = rows
        .iter()
        .map(|r| 1.0 / r.iter().map(|e| e.1).sum::<f64>().max(1e-9).sqrt())
        .collect();
    for (i, r) in rows.iter_mut().enumerate() {
        for e in r.iter_mut() {
            e.1 *= scale[i] * scale[e.0];
        }
    }
    Sparse { rows }
}

/// Eigenvalues (descending) and eigenvectors (columns) of a small symmetric
/// matrix by cyclic Jacobi rotations.
fn jacobi_eigen(mut a: Vec<Vec<f64>>) -> (Vec<f64>, Columns) {
    let p = a.len();
    let mut v: Vec<Vec<f64>> = (0..p)
        .map(|i| (0..p).map(|j| f64::from(u8::from(i == j))).collect())
        .collect();
    for _ in 0..100 {
        let off: f64 = (0..p)
            .flat_map(|i| (i + 1..p).map(move |j| (i, j)))
            .map(|(i, j)| a[i][j] * a[i][j])
            .sum();
        if off < 1e-24 {
            break;
        }
        for i in 0..p {
            for j in i + 1..p {
                if a[i][j].abs() < 1e-300 {
                    continue;
                }
                let theta = (a[j][j] - a[i][i]) / (2.0 * a[i][j]);
                let t = theta.signum() / (theta.abs() + (theta * theta + 1.0).sqrt());
                let c = 1.0 / (t * t + 1.0).sqrt();
                let s = t * c;
                // Columns i, j, then rows i, j (i < j) of `a`.
                for row in a.iter_mut() {
                    let (x, y) = (row[i], row[j]);
                    row[i] = c * x - s * y;
                    row[j] = s * x + c * y;
                }
                let (upper, lower) = a.split_at_mut(j);
                for (x, y) in upper[i].iter_mut().zip(lower[0].iter_mut()) {
                    let (u, w) = (*x, *y);
                    *x = c * u - s * w;
                    *y = s * u + c * w;
                }
                for row in v.iter_mut() {
                    let (x, y) = (row[i], row[j]);
                    row[i] = c * x - s * y;
                    row[j] = s * x + c * y;
                }
            }
        }
    }
    let mut order: Vec<usize> = (0..p).collect();
    order.sort_by(|&x, &y| a[y][y].total_cmp(&a[x][x]));
    let values = order.iter().map(|&i| a[i][i]).collect();
    let vectors = order
        .iter()
        .map(|&col| v.iter().map(|row| row[col]).collect())
        .collect();
    (values, vectors)
}

/// Gram-Schmidt (twice, for accuracy); a dependent column is replaced by a random one.
fn orthonormalize(q: &mut Columns, rng: &mut XorShift) {
    for c in 0..q.len() {
        for _ in 0..8 {
            for _ in 0..2 {
                for b in 0..c {
                    let d = dot(&q[c], &q[b]);
                    let basis = q[b].clone();
                    q[c].iter_mut().zip(&basis).for_each(|(x, y)| *x -= d * y);
                }
            }
            let norm = dot(&q[c], &q[c]).sqrt();
            if norm > 1e-10 {
                q[c].iter_mut().for_each(|x| *x /= norm);
                break;
            }
            q[c].iter_mut().for_each(|x| *x = rng.next_f64() - 0.5);
        }
    }
}

/// `columns · rotation`: column `c` of the result is `sum_k columns[k] * rotation[c][k]`.
fn rotate(columns: &Columns, rotation: &Columns) -> Columns {
    rotation
        .iter()
        .map(|coef| {
            let mut out = vec![0.0; columns[0].len()];
            for (col, w) in columns.iter().zip(coef) {
                out.iter_mut().zip(col).for_each(|(o, x)| *o += w * x);
            }
            out
        })
        .collect()
}

/// The `p` largest eigenpairs of `m`: block subspace iteration on `m + I`
/// (eigenvalues of `m` are in `[-1, 1]`, so the shift keeps them positive),
/// Rayleigh-Ritz on the small projected matrix after every step.
fn top_eigen(m: &Sparse, p: usize, rng: &mut XorShift) -> (Vec<f64>, Columns) {
    let n = m.rows.len();
    let p = p.min(n);
    let mut q: Columns = (0..p)
        .map(|_| (0..n).map(|_| rng.next_f64() - 0.5).collect())
        .collect();
    orthonormalize(&mut q, rng);
    let mut values = vec![f64::INFINITY; p];
    for iteration in 0..MAX_ITERATIONS {
        let y = m.mul(&q);
        let projected: Vec<Vec<f64>> = (0..p)
            .map(|a| {
                (0..p)
                    .map(|b| (dot(&q[a], &y[b]) + dot(&q[b], &y[a])) / 2.0)
                    .collect()
            })
            .collect();
        let (ritz, vectors) = jacobi_eigen(projected);
        let delta = ritz
            .iter()
            .zip(&values)
            .map(|(a, b)| (a - b).abs())
            .fold(0.0, f64::max);
        let ritz_q = rotate(&q, &vectors);
        let ritz_y = rotate(&y, &vectors);
        values = ritz;
        if delta < TOLERANCE || iteration + 1 == MAX_ITERATIONS {
            return (values, ritz_q);
        }
        // (m + I) q
        q = ritz_y;
        q.iter_mut()
            .zip(&ritz_q)
            .for_each(|(a, b)| a.iter_mut().zip(b).for_each(|(x, y)| *x += y));
        orthonormalize(&mut q, rng);
    }
    (values, q)
}

/// Number of clusters from the largest jump between consecutive eigenvalues
/// `1 - mu` of the Laplacian, `k` in `2..=MAX_K`.
fn eigengap_k(mu: &[f64]) -> usize {
    let lam: Vec<f64> = mu.iter().map(|m| 1.0 - m).collect();
    let mut best = (2, f64::NEG_INFINITY);
    for k in 2..=MAX_K.min(lam.len().saturating_sub(1)) {
        let gap = lam[k] - lam[k - 1];
        if gap > best.1 {
            best = (k, gap);
        }
    }
    best.0
}

/// Cluster labels `0..k` of the unit vectors `x` (weights: durations) and `k`;
/// `k = None`: by the eigengap.
pub(super) fn spectral_labels(x: &[Vec<f64>], w: &[f64], k: Option<usize>) -> (Vec<usize>, usize) {
    let n = x.len();
    let neighbors = ((NEIGHBOR_SHARE * n as f64).round() as usize)
        .max(MIN_NEIGHBORS)
        .min(n - 1);
    let graph = normalized_affinity(x, neighbors);
    let mut rng = XorShift::new(SEED);
    let (mu, vectors) = top_eigen(&graph, BLOCK, &mut rng);
    let k = k
        .map_or_else(|| eigengap_k(&mu), |k| k.clamp(2, MAX_K))
        .min(vectors.len());
    let rows: Vec<Vec<f64>> = (0..n)
        .map(|i| {
            let row: Vec<f64> = vectors[..k].iter().map(|v| v[i]).collect();
            let norm = dot(&row, &row).sqrt();
            row.into_iter()
                .map(|x| if norm > 1e-9 { x / norm } else { x })
                .collect()
        })
        .collect();
    (kmeans(&rows, w, k, KMEANS_RESTARTS, &mut rng), k)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jacobi_finds_the_eigenpairs_of_a_symmetric_matrix() {
        let a = vec![
            vec![4.0, 1.0, 0.5],
            vec![1.0, 3.0, 0.2],
            vec![0.5, 0.2, 1.0],
        ];
        let (values, vectors) = jacobi_eigen(a.clone());
        assert!(values.windows(2).all(|w| w[0] >= w[1]));
        for (value, vector) in values.iter().zip(&vectors) {
            for i in 0..3 {
                let av: f64 = (0..3).map(|j| a[i][j] * vector[j]).sum();
                assert!((av - value * vector[i]).abs() < 1e-9);
            }
        }
    }

    #[test]
    fn eigengap_picks_the_jump() {
        // Three eigenvalues near 1 (Laplacian near 0), then a jump.
        let mu = [1.0, 0.999, 0.998, 0.4, 0.3, 0.2, 0.1, 0.0, -0.1, -0.2, -0.3];
        assert_eq!(eigengap_k(&mu), 3);
    }
}

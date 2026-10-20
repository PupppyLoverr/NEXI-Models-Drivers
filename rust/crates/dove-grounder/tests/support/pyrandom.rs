//! CPython 3.13's `random.Random` (`Lib/random.py` over `Modules/_randommodule.c`),
//! reproduced exactly for integer seeds: the same MT19937 stream and the same
//! way each method consumes it, so a port of Python code that draws from
//! `random.Random(seed)` makes the same choices.

const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER_MASK: u32 = 0x8000_0000;
const LOWER_MASK: u32 = 0x7fff_ffff;

/// `random.Random`: MT19937 seeded the way `random_seed` seeds it from an int.
pub struct PyRandom {
    mt: [u32; N],
    index: usize,
}

impl PyRandom {
    /// `random.Random(seed)` for a non-negative int seed.
    pub fn new(seed: u64) -> Self {
        Self::from_u128(seed as u128)
    }

    /// `random.Random(seed)` for a non-negative int seed up to 128 bits.
    ///
    /// `random_seed` takes `abs(seed)`, splits it into 32-bit words, least
    /// significant first (a zero seed is the single word `0`), and runs
    /// `init_by_array` over them.
    pub fn from_u128(seed: u128) -> Self {
        let mut key = Vec::new();
        let mut rest = seed;
        while rest != 0 {
            key.push(rest as u32);
            rest >>= 32;
        }
        if key.is_empty() {
            key.push(0);
        }
        let mut rng = Self {
            mt: [0; N],
            index: N,
        };
        rng.init_by_array(&key);
        rng
    }

    /// `init_genrand`.
    fn init_genrand(&mut self, s: u32) {
        self.mt[0] = s;
        for i in 1..N {
            let prev = self.mt[i - 1];
            self.mt[i] = 1_812_433_253u32
                .wrapping_mul(prev ^ (prev >> 30))
                .wrapping_add(i as u32);
        }
        self.index = N;
    }

    /// `init_by_array`.
    fn init_by_array(&mut self, key: &[u32]) {
        self.init_genrand(19_650_218);
        let mut i = 1usize;
        let mut j = 0usize;
        let len = key.len();
        for _ in 0..N.max(len) {
            let prev = self.mt[i - 1];
            self.mt[i] = (self.mt[i] ^ (prev ^ (prev >> 30)).wrapping_mul(1_664_525))
                .wrapping_add(key[j])
                .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
            if j >= len {
                j = 0;
            }
        }
        for _ in 0..N - 1 {
            let prev = self.mt[i - 1];
            self.mt[i] = (self.mt[i] ^ (prev ^ (prev >> 30)).wrapping_mul(1_566_083_941))
                .wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
        }
        self.mt[0] = 0x8000_0000;
    }

    /// `genrand_uint32`.
    fn genrand_u32(&mut self) -> u32 {
        if self.index >= N {
            let mag = |y: u32| if y & 1 == 0 { 0 } else { MATRIX_A };
            for kk in 0..N - M {
                let y = (self.mt[kk] & UPPER_MASK) | (self.mt[kk + 1] & LOWER_MASK);
                self.mt[kk] = self.mt[kk + M] ^ (y >> 1) ^ mag(y);
            }
            for kk in N - M..N - 1 {
                let y = (self.mt[kk] & UPPER_MASK) | (self.mt[kk + 1] & LOWER_MASK);
                self.mt[kk] = self.mt[kk + M - N] ^ (y >> 1) ^ mag(y);
            }
            let y = (self.mt[N - 1] & UPPER_MASK) | (self.mt[0] & LOWER_MASK);
            self.mt[N - 1] = self.mt[M - 1] ^ (y >> 1) ^ mag(y);
            self.index = 0;
        }
        let mut y = self.mt[self.index];
        self.index += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^ (y >> 18)
    }

    /// `random()`: a 53-bit float in [0, 1).
    pub fn random(&mut self) -> f64 {
        let a = (self.genrand_u32() >> 5) as f64;
        let b = (self.genrand_u32() >> 6) as f64;
        (a * 67_108_864.0 + b) * (1.0 / 9_007_199_254_740_992.0)
    }

    /// `getrandbits(k)` for `k <= 128`: 32-bit words, least significant
    /// first, the last one cut to its top `k % 32` bits.
    pub fn getrandbits(&mut self, k: u32) -> u128 {
        assert!(k <= 128, "getrandbits({k}) is beyond this port");
        if k == 0 {
            return 0;
        }
        if k <= 32 {
            return (self.genrand_u32() >> (32 - k)) as u128;
        }
        let mut out = 0u128;
        let mut left = k;
        let mut shift = 0;
        while left > 0 {
            let mut r = self.genrand_u32();
            if left < 32 {
                r >>= 32 - left;
            }
            out |= (r as u128) << shift;
            shift += 32;
            left = left.saturating_sub(32);
        }
        out
    }

    /// `_randbelow_with_getrandbits(n)`: `k = n.bit_length()` bits, rejected
    /// until below `n`.
    pub fn randbelow(&mut self, n: u64) -> u64 {
        let k = 64 - n.leading_zeros();
        let mut r = self.getrandbits(k) as u64;
        while r >= n {
            r = self.getrandbits(k) as u64;
        }
        r
    }

    /// `randrange(stop)`.
    pub fn randrange(&mut self, stop: i64) -> i64 {
        assert!(stop > 0, "empty range for randrange()");
        self.randbelow(stop as u64) as i64
    }

    /// `randrange(start, stop)`.
    pub fn randrange2(&mut self, start: i64, stop: i64) -> i64 {
        let width = stop - start;
        assert!(width > 0, "empty range in randrange({start}, {stop})");
        start + self.randbelow(width as u64) as i64
    }

    /// `randint(a, b)` = `randrange(a, b + 1)`.
    pub fn randint(&mut self, a: i64, b: i64) -> i64 {
        self.randrange2(a, b + 1)
    }

    /// `choice(seq)`: `seq[_randbelow(len(seq))]`.
    pub fn choice<'a, T>(&mut self, seq: &'a [T]) -> &'a T {
        assert!(!seq.is_empty(), "Cannot choose from an empty sequence");
        &seq[self.randbelow(seq.len() as u64) as usize]
    }

    /// `shuffle(x)`.
    pub fn shuffle<T>(&mut self, x: &mut [T]) {
        for i in (1..x.len()).rev() {
            let j = self.randbelow(i as u64 + 1) as usize;
            x.swap(i, j);
        }
    }

    /// `sample(population, k)` (no `counts`): a pool when the population is
    /// small next to a `k`-element set, else rejection against the set of
    /// indices already chosen.
    pub fn sample<T: Clone>(&mut self, population: &[T], k: usize) -> Vec<T> {
        let n = population.len();
        assert!(k <= n, "Sample larger than population or is negative");
        let mut setsize = 21usize;
        if k > 5 {
            // 4 ** _ceil(_log(k * 3, 4)); k * 3 is never a power of 4.
            let exp = ((k * 3) as f64).ln() / 4f64.ln();
            setsize += 4usize.pow(exp.ceil() as u32);
        }
        let mut result = Vec::with_capacity(k);
        if n <= setsize {
            let mut pool: Vec<T> = population.to_vec();
            for i in 0..k {
                let j = self.randbelow((n - i) as u64) as usize;
                result.push(pool[j].clone());
                pool[j] = pool[n - i - 1].clone();
            }
        } else {
            let mut selected = std::collections::HashSet::new();
            for _ in 0..k {
                let mut j = self.randbelow(n as u64) as usize;
                while selected.contains(&j) {
                    j = self.randbelow(n as u64) as usize;
                }
                selected.insert(j);
                result.push(population[j].clone());
            }
        }
        result
    }

    /// `uniform(a, b)` = `a + (b - a) * random()`.
    pub fn uniform(&mut self, a: f64, b: f64) -> f64 {
        a + (b - a) * self.random()
    }
}

#[cfg(test)]
mod tests {
    use super::PyRandom;

    // Reference values printed by CPython 3.13's `random` module.

    #[test]
    fn matches_cpython_stream() {
        let mut r = PyRandom::new(31337);
        let bits: Vec<u64> = (0..3).map(|_| r.random().to_bits()).collect();
        assert_eq!(
            bits,
            [0x3fe5c260ba04740a, 0x3fc5dab974d447c8, 0x3fee5f455e60df75]
        );
        let got: Vec<u128> = [1, 7, 32, 33, 64, 100]
            .iter()
            .map(|&k| r.getrandbits(k))
            .collect();
        assert_eq!(
            got,
            [
                0,
                26,
                3551084662,
                772076153,
                10234245951101125297,
                1155756214032968201439001130643
            ]
        );
        let got: Vec<u64> = [1, 2, 3, 10, 1000, (1 << 40) + 3]
            .iter()
            .map(|&n| r.randbelow(n))
            .collect();
        assert_eq!(got, [0, 1, 0, 0, 82, 410729249105]);
        assert_eq!(
            [
                r.randrange(7),
                r.randrange2(3, 9),
                r.randint(99, 999),
                r.randint(1, 99999)
            ],
            [6, 3, 805, 20384]
        );
        let letters: Vec<char> = "abcdefg".chars().collect();
        let got: String = (0..5).map(|_| *r.choice(&letters)).collect();
        assert_eq!(got, "dgbdb");
        let mut x: Vec<i32> = (0..10).collect();
        r.shuffle(&mut x);
        assert_eq!(x, [0, 7, 6, 8, 1, 4, 2, 3, 9, 5]);
        let range = |n: i32| (0..n).collect::<Vec<_>>();
        assert_eq!(r.sample(&range(20), 5), [11, 1, 13, 5, 14]);
        // n > setsize: the selected-set branch.
        assert_eq!(r.sample(&range(30), 2), [11, 22]);
        assert_eq!(r.sample(&range(100), 8), [93, 50, 9, 65, 64, 11, 61, 85]);
        // k > 5 widens setsize to 85, so 50 takes the pool branch.
        assert_eq!(r.sample(&range(50), 8), [15, 29, 0, 8, 41, 49, 3, 47]);
        assert_eq!(r.uniform(0.0, 1400.0).to_bits(), 0x4051f13aca2b9ae5);
        assert_eq!(r.uniform(24.0, 60.0).to_bits(), 0x4049295b7e51dd32);
    }

    #[test]
    fn matches_cpython_int_seeding() {
        let cases: [(u128, u128, u64); 6] = [
            (0, 3626764237, 0x3feb0580f98a7dbe),
            (1, 577090037, 0x3fc132d8f91b7584),
            (1 << 32, 485306839, 0x3fbced31cb3df170),
            ((1 << 32) + 5, 675479763, 0x3fc4218067c49768),
            ((1 << 64) + 7, 4134331577, 0x3feecd9c9456e992),
            (
                123456789012345678901234567890,
                3124625047,
                0x3fe747bfd0e1ccc9,
            ),
        ];
        for (seed, word, bits) in cases {
            assert_eq!(
                PyRandom::from_u128(seed).getrandbits(32),
                word,
                "seed {seed}"
            );
            assert_eq!(
                PyRandom::from_u128(seed).random().to_bits(),
                bits,
                "seed {seed}"
            );
        }
    }
}

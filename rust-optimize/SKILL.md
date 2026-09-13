---
name: rust-optimize
description: >
  Load when the user asks to "optimize this Rust code", "make this Rust more concise",
  "reduce Rust boilerplate", "refactor Rust for performance", "use bit tricks in Rust",
  "simplify this Rust function", or "make this Rust elegant".
  Covers: conciseness, iterator/combinator rewrites, bit manipulation replacements,
  branch elimination, allocation reduction, and idiomatic Rust refactoring.
  Do not use for new feature development, architecture design, async runtime selection,
  FFI binding, or cross-platform porting. Do not use for non-Rust languages.
---

# Rust Optimize

Optimize existing Rust code for **conciseness**, **performance**, and **elegance** — without changing observable behavior.

## Core Mandate

1. **Logic invariant**: input/output behavior, error semantics, and side effects must not change.
2. **Minimize lines**: prefer combinators, pattern sugar, and standard library over hand-rolled loops.
3. **Maximize throughput**: prefer zero-allocation, branch-free, and cache-friendly patterns.
4. **Stay readable**: a 1-liner that nobody can review is worse than 3 clear lines.

## Optimization Procedure

```
1. Read the target code. Identify return type, side effects, error paths.
2. Run mental "before" snapshot: what does this code do? (never skip)
3. Apply passes in order: Conciseness → Performance → Elegance (see below).
4. After each pass, verify logic invariant by tracing edge cases.
5. Present diff with per-change rationale.
6. Run verification: cargo check && cargo clippy -- -D warnings && cargo test
7. If verification fails → revert that change, proceed to next.
```

## Pass 1 — Conciseness

Apply highest-value rewrites first. Stop when further reduction hurts clarity.

### Pattern Table

| Before | After | When to apply |
|---|---|---|
| `match x { Some(v) => f(v), None => default }` | `x.map_or(default, f)` | No side effects in `None` arm |
| `match x { A => true, B => true, _ => false }` | `matches!(x, A \| B)` | Boolean result only |
| `if let Some(v) = x { v } else { return Err(e) }` | `let v = x.ok_or(e)?;` | Early-return error |
| `let x = match … { Ok(v) => v, Err(e) => return Err(e.into()) }` | `let x = …?;` | Direct `?` propagation |
| `if condition { return Err(…) }` | `ensure!(condition, …)` | With `anyhow` — or keep `if` without crate dep |
| `let mut v = Vec::new(); for item in iter { v.push(f(item)); }` | `let v: Vec<_> = iter.map(f).collect();` | Pure transform, no early break |
| `iter.filter(…).count() > 0` | `iter.any(…)` | Existence check |
| `iter.filter(…).count() == 0` | `!iter.any(…)` | Absence check |
| `x.len() == 0` / `x.len() > 0` | `x.is_empty()` / `!x.is_empty()` | Always |
| `foo.clone()` passed to consuming fn | Move `foo` or borrow | `foo` not used after |
| `format!("{}", x)` where x: impl Display | `x.to_string()` | Simple string conversion |
| `&String` / `&Vec<T>` in fn params | `&str` / `&[T]` | Unless API requires owned |
| `if let Some(x) = a { … } else if let Some(x) = b { … }` | `let x = a.or(b).…` | Merging Option chains |
| Manual index loop `for i in 0..v.len() { v[i] }` | `for item in &v` or `v.iter().enumerate()` | Always unless index arithmetic needed |
| `match result { Ok(v) => Ok(f(v)), Err(e) => Err(e) }` | `result.map(f)` | Always |
| Multi-field struct update with 1 field changed | `Struct { field: new_val, ..old }` | Struct is `Copy` or moved |
| Nested `if let` / `if` chains | `let … else { }` (let-else, stable since 1.65) | Guard clause pattern |

### Combinator Cheat Sheet

```
Option:  map → and_then → or_else → unwrap_or_else → filter → zip
Result:  map → map_err → and_then → or_else → unwrap_or_else
Iterator: map → filter → filter_map → flat_map → fold → scan → chain
          take → skip → zip → enumerate → peekable → chunks (slice)
          any → all → find → find_map → position → sum → product
```

**Rule**: if you chain more than 4 combinators, extract a named helper or use a `for` loop — whichever reads clearer.

## Pass 2 — Performance

Apply only where the code is on a hot path or processes bulk data. Do not micro-optimize cold setup code.

### Bit Manipulation Replacements

| Before | After | Condition |
|---|---|---|
| `x % 2 == 0` | `x & 1 == 0` | `x` is unsigned or known non-negative |
| `x * 2` / `x / 2` | `x << 1` / `x >> 1` | Unsigned integers; compiler usually does this, prefer for clarity of intent |
| `x % (1 << n)` | `x & ((1 << n) - 1)` | Power-of-2 modulo |
| `x.pow(2)` | `x * x` | Avoid function call overhead |
| `(x + (align - 1)) / align * align` | `(x + align - 1) & !(align - 1)` | `align` is power of 2 |
| Boolean flag set: `HashSet<EnumVariant>` | `u32` / `u64` bitflags | ≤ 64 variants, `bitflags` crate or manual |
| `if a { 1 } else { 0 }` | `a as u32` | `a: bool` — zero-branch cast |
| `if flag { x } else { y }` | `[y, x][flag as usize]` | Both `x`, `y` are cheap; avoid if side effects — prefer only when branch prediction is poor |
| `x.abs()` for integers | `(x ^ (x >> 31)) - (x >> 31)` | Only in SIMD-like hot loops; otherwise `.abs()` is clearer |
| Count set bits | `x.count_ones()` | Always — maps to `popcnt` intrinsic |
| Leading/trailing zeros | `x.leading_zeros()` / `x.trailing_zeros()` | Always — maps to `clz`/`ctz` |
| Is power of 2 | `x.is_power_of_two()` | Always — cleaner than `x & (x-1) == 0` |
| Next power of 2 | `x.next_power_of_two()` | Always |
| Log2 of power-of-2 | `x.trailing_zeros()` | `x` guaranteed power of 2 |

### Allocation & Copy Reduction

| Pattern | Optimization |
|---|---|
| `String` param only read | Accept `&str` or `impl AsRef<str>` |
| Returned `String` sometimes borrowed | `Cow<'_, str>` |
| `vec![0u8; n]` then immediate overwrite | `Vec::with_capacity(n)` + unsafe `set_len` (with SAFETY doc) or `MaybeUninit` |
| `to_vec()` / `clone()` for temporary | Borrow or use slice |
| `collect::<Vec<_>>()` only to iterate again | Chain iterators directly |
| Small fixed-size collections | `[T; N]` / `ArrayVec` / `SmallVec` |
| Frequent small allocs in hot loop | Arena (`bumpalo`) or pool |
| `Box<dyn Trait>` in hot path | `enum_dispatch` or static dispatch |

### Branch Elimination

| Pattern | Optimization |
|---|---|
| `if unlikely_condition { cold_path } else { hot_path }` | `#[cold]` on cold fn + `std::hint::unlikely` (nightly) or structure so hot path is fallthrough |
| Match with many arms | Consider lookup table (`const` array) |
| Repeated bounds checks in loop | Use `get_unchecked` (with SAFETY proof of bounds) or iterator instead |
| Sort + dedup | `sort_unstable` + `dedup` (unstable sort is faster, no allocation) |

## Pass 3 — Elegance

### Structural Refinements

- **Guard clause**: flip `if happy { long_body } else { return err }` → `if !happy { return err; }` then unindented body.
- **Single responsibility**: if a function has 2+ conceptual stages, split into named helpers.
- **Type-driven**: replace `bool` params with 2-variant enum. Replace `(u32, u32)` with named struct.
- **Const correctness**: `const fn` where possible. `const` lookup tables over runtime init.
- **Builder pattern**: if a struct has ≥4 optional fields, consider builder.
- **Newtype**: wrap primitive IDs (`UserId(u64)`) to prevent parameter swapping bugs.

### Naming

- Functions: verb phrase (`compute_hash`, `drain_queue`). Not `hash` (noun ambiguity) or `do_thing`.
- Booleans: `is_`, `has_`, `should_`, `can_` prefix.
- Iterators / closures: `|item|` not `|x|`; `|entry|` not `|e|` (reserve `e` for errors).
- Avoid `_val`, `_data`, `_info` suffixes unless genuinely disambiguating.

## Known Gotchas

- `x << 1` on `i32` can overflow differently than `x * 2` — ensure unsigned or wrapping semantics.
  → Use `wrapping_shl` / `wrapping_mul` if overflow is intentional.
- Replacing `if/else` with branchless `[y, x][flag as usize]` can be **slower** if the branch predictor is effective — benchmark first.
- `matches!()` cannot bind variables — use `match` if you need the inner value.
- `.or_else(|| …)` allocates a closure; for trivial `Option::or` prefer `.or(fallback)`.
- Removing `.clone()` may move a value that's used later — compiler will catch, but trace usage first.
- `sort_unstable` does not preserve equal-element order — only use when order among equals is irrelevant.
- `get_unchecked` is `unsafe` — requires a `// SAFETY:` comment proving bounds. Never use without proof.
- Iterator chains with side effects (`.inspect()`, `.for_each()`) are lazy until consumed — ensure terminal operation exists.

## Verification Checklist

After all passes:

- [ ] `cargo check` — no compile errors
- [ ] `cargo clippy --all-targets -- -D warnings` — no new warnings
- [ ] `cargo test` — all tests still pass (logic invariant)
- [ ] Each `unsafe` block has accurate `// SAFETY:` comment
- [ ] No `.unwrap()` introduced on fallible paths (use `?` or `expect("reason")`)
- [ ] Bit operations only on unsigned types or with explicit wrapping/checked semantics
- [ ] Diff is explainable: every removed line has a rationale

## Anti-Trigger Clarification

This skill does **not** cover:
- Adding new features or changing public API signatures
- Choosing between `tokio` vs `async-std` or architectural decisions
- FFI/unsafe boundary design (use `rust-pro` or project-specific skills)
- Non-Rust languages (use `simplify` for general code cleanup)
- Formatting — that's `cargo fmt`

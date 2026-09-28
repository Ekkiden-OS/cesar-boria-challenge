# Design rationale

## Architecture and request flow

The implementation separates three concerns:

```text
FastAPI / HTTP -> exact JSON and domain validation -> exact optimizer -> JSON response
```

`powerplant.main` owns the HTTP contract, logging, status mapping, and the thread-pool boundary.
`powerplant.validation` turns the original JSON bytes into immutable domain objects and exact
numeric representations. `powerplant.optimizer` knows nothing about HTTP: it accepts a validated
`ProductionProblem`, enforces its work envelope, and either returns a plan or raises a specific
exception.

The endpoint deliberately reads the raw request body. `json.loads` receives
`parse_int=Decimal` and `parse_float=Decimal`, so a literal such as `0.10000000000000001` is never
rounded through binary `float` before validation. Malformed JSON and invalid domain values map to
HTTP 400; a valid but mathematically infeasible problem maps to 422. Resource refusal and unexpected
failure are kept separate as 413 and 500. The 500 response is generic while the full exception is
logged server-side.

## Exact domain model

Power is discretized in integer tenths of MW. The load must already lie on that grid and becomes
`L = 10 * load`. A thermal plant may be off (`0`) or produce any grid value inside its physical
bounds. Therefore a non-grid `pmin` is rounded up and a non-grid `pmax` is rounded down when deriving
admissible integer bounds; the original `Decimal` values are retained as domain data.

Prices, efficiencies, bounds, and wind percentage enter as `Decimal`. Marginal costs are converted
to `Fraction`, so division by efficiency and accumulated costs remain rationally exact. Binary
floating point appears only at the final JSON response boundary, after integer tenths have already
fixed every output; values such as `output / 10` are contract-safe numeric representations of that
discrete result.

The challenge says a wind turbine is either switched on at the power implied by `pmax * wind%`, or
switched off. This implementation consequently models wind as all-or-nothing, not continuously
curtailable. The available value must itself lie on the `0.1 MW` response grid and within the plant's
`pmin/pmax`; otherwise that turbine can only be off. The statement is somewhat ambiguous about
curtailment and about non-grid wind availability. This strict interpretation follows its
“either switched-on ... or switched off” wording and its exact output-grid requirement.

All plant types use `pmin/pmax` as physical on-state bounds. Although the prose emphasizes gas-fired
minimum output, applying the supplied bounds consistently to thermal plants avoids silently ignoring
input constraints. Plant names must be unique so reconstruction and output identity are unambiguous.

## Objective and why merit-order greedy is insufficient

The base marginal costs per electrical MWh are:

```text
gas-fired: gas_price / efficiency
turbojet:  kerosine_price / efficiency
wind:      0
```

Plants are processed in stable marginal-cost order, but cost order alone is not an optimizer.
Minimum-output commitments create gaps: greedily filling a cheap plant can leave a remainder smaller
than an expensive plant's `pmin`, even though backing the cheap plant down would produce a feasible
and optimal combination. Exact-load feasibility and cost minimization must therefore be considered
together.

## Dynamic-programming state and recurrence

After processing `i` plants, the dynamic program maps each reachable total `x` to a state containing
the exact minimum cost for `x` and the tuple of outputs that produced it. A lower cost wins. Equal
costs prefer the lexicographically larger output tuple. Since plants are processed in stable
marginal-cost order, this rule makes the public plan deterministic.

For a thermal plant with marginal cost `c` per MW and allowed positive outputs `a..b` tenths, the
clear original transition was:

```text
off:     D_i(x) = D_(i-1)(x)
on(q):   D_i(x) = D_(i-1)(x-q) + c*q/10,  q in [a,b]
```

The initial state is total zero with zero cost and an empty tuple. After the final plant, absence of
state `L` proves infeasibility. Wind uses a separate two-choice transition: off or its one exact
available output.

## Thermal sliding-window transformation

Explicitly enumerating every `q` repeats almost the same predecessor interval for adjacent targets.
For a fixed target `x`, an active thermal plant can follow exactly those previous totals `y` where:

```text
a <= x-y <= b
x-b <= y <= x-a
```

The candidate cost is:

```text
D(y) + c*(x-y)/10
= D(y) - (c/10)*y + (c/10)*x
```

For fixed `x`, the last term is common. Define `A(y) = D(y) - (c/10)*y`. The best active
predecessor is the minimum `A(y)` in the sliding interval `[x-b, x-a]`; `(c/10)*x` is added back
after selection. Because all terms are `Fraction`, this is algebraically equivalent for positive,
zero, and negative marginal costs.

Each monotonic-deque element stores:

- `previous_total`: predecessor `y`;
- `adjusted_cost`: exact `A(y)`;
- `state`: its exact original cost and complete prefix output tuple.

Targets `x` are visited from `0` through `L`:

1. Existing predecessor `y = x-a` enters the deque.
2. Entries with `y < x-b` leave from the left because they have expired.
3. Before insertion, entries leave from the right while the newcomer has lower adjusted cost, or
   equal adjusted cost and a lexicographically larger prefix. They can never win a current or future
   window, and the newer candidate expires no earlier.
4. The left entry is the best active predecessor. The off state is compared separately.

Equal transformed costs also have equal final costs for a target. Comparing their prefixes therefore
preserves the original full-tuple tie-break. Wind remains all-or-nothing and does not use the deque.

## Reconstruction and output order

Every retained state stores its complete prefix tuple. A transition appends zero or the selected
output, so no separate backtracking structure is needed. The final tuple is zipped with plants in
stable merit order. This produces deterministic output and matches the supplied `response3.json`,
but retaining full prefixes is also the main reason the concrete complexity exceeds the abstract
deque bound.

## Complexity of this implementation

Let `n` be the number of plants, `L` the requested load in tenths, `W_i` the number of positive
discrete outputs of thermal plant `i`, and `i` the current prefix length.

The original thermal transition considered up to `O(L * W_i)` candidates for plant `i`. Each
candidate also performed exact rational arithmetic and created a length-`i` tuple. Tuple-copy work
alone was therefore `O(i * L * W_i)`, and across plants
`O(sum(i * L * W_i))` in the worst case.

With the deque, every predecessor enters once and leaves at most once. A thermal layer performs
`O(L)` high-level target, dictionary, append, and amortized deque operations; a wind layer performs
at most two transitions per reachable total. That abstract transition core is `O(nL)`. It is not the
total bound of this concrete implementation:

- high-level DP/deque operations: `O(nL)`;
- worst-case tuple copying and lexicographic comparison: `O(sum(iL)) = O(n^2 L)`;
- retained state memory at layer `i`: `O(iL)` for stored tuples, plus `O(L)` state/deque references.

These counts also do not make `Fraction` constant-time. Numerator and denominator sizes depend on
the decimal inputs and accumulated values; arithmetic, reduction, and comparison inherit the bit
complexity of arbitrary-size integers. The deque reduces the number of rational operations from
`O(sum(L * W_i))` to `O(nL)`, but their individual cost is input-dependent.

The algorithm is pseudopolynomial: `L` is a numeric magnitude (`10 * load`), not the number of bits
needed to encode the load. Doubling the requested MW approximately doubles the target traversal even
when the JSON representation grows by only one digit.

## Operational resource envelope

Before sorting plants, creating the first state dictionary, allocating a deque, or traversing
`range(L + 1)`, the optimizer requires:

```text
L <= 200,000
(L + 1) * number_of_plants <= 2,000,000
```

The first limit corresponds to `20,000 MW` and caps any one integer-indexed target range. The second
is a conservative count of potential `(plant prefix, accumulated total)` cells. It is not a precise
memory formula because two DP layers, growing tuples, and `Fraction` objects have different sizes.

Plant `pmax` is deliberately absent from the envelope: transitions never target totals above `L`, so
a huge capacity with a small load does not itself create additional states. Exceeding an operational
limit raises HTTP 413: the service declines the work and feasibility remains unknown. HTTP 422 means
the bounded DP actually completed and proved no exact plan exists.

## Optional CO2 objective

CO2 is disabled by default. `INCLUDE_CO2=true`, read at request time from the server process's
environment, changes only gas-fired marginal cost:

```text
gas_price / efficiency + 0.3 * co2_price
```

The challenge states that each generated MWh emits `0.3 ton`, so the emissions term is not divided
by efficiency. `0.3` and the price remain exact through `Decimal` and `Fraction`. Turbojet and wind
costs are unchanged. This modifies objective coefficients, not feasible states or the DP recurrence,
so the optimizer architecture needs no special CO2 branch.

## HTTP execution and concurrency

FastAPI performs body reading and validation at the asynchronous boundary, then calls the synchronous
optimizer through `run_in_threadpool`. This prevents one optimization from directly blocking the
event-loop thread, allowing the server to continue servicing lightweight asynchronous work.

It does not make this pure-Python CPU-bound DP faster, remove the GIL, provide process isolation, or
guarantee throughput under concurrent expensive requests. The explicit work envelope limits each
request, but there is no global concurrency budget, queue, timeout, cancellation propagation, or
multi-process worker policy in this challenge-sized service.

## Verification and benchmark evidence

Tests cover the official fixtures, exact numeric parsing, validation, HTTP statuses and recovery,
resource limits, optional CO2, explicit edge cases, and 150 reproducible small problems compared
with an independent Cartesian-product oracle. The oracle enumerates plant outputs rather than
reusing the production DP.

Run the current benchmark with:

```powershell
.\.venv\Scripts\python benchmarks\benchmark_official.py
```

The optimization was originally measured on Windows with Python 3.13.15, using the same environment
and official fixtures:

| Fixture | Explicit enumeration | Monotonic deque | Speedup |
|---|---:|---:|---:|
| `payload1.json` | 20.248564 s | 0.068753 s | 294x |
| `payload2.json` | 20.987766 s | 0.063671 s | 330x |
| `payload3.json` | 69.560032 s | 0.124154 s | 560x |
| Total | 110.797651 s | 0.257650 s | 430x |

Before/after serialized-plan SHA-256 prefixes were identical: `865f6a7a765c`, `d3a0b840b571`, and
`4521da985a5e`. These measurements demonstrate the observed bottleneck and improvement on that
machine; they are not universal latency or capacity guarantees. Hardware, interpreter, inputs,
warm-up, concurrent load, and repetition methodology all affect timings.

## Known limitations and production improvements

This is a deliberately bounded challenge solution, not a complete unit-commitment platform. A
production system would consider time-coupled schedules, ramp rates, start/stop costs, minimum up/down
times, reserves, storage, network constraints, forecasts, and explicit wind-curtailment policy. It
would also need authentication, rate and concurrency limits, request deadlines and cancellation,
metrics and tracing, structured logs, health/readiness endpoints, multiple worker/process sizing,
and load testing.

For larger single-period instances, reconstruction could store predecessor links instead of copying
full tuples, and tie-breaking could use compact ranks. A dense cost array may reduce dictionary
overhead. Beyond the pseudopolynomial envelope, a different formulation or specialized solver would
be appropriate, with the trade-off that the challenge explicitly asks for a self-written algorithm.

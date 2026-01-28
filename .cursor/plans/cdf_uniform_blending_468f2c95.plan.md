---
name: CDF Uniform Blending
overview: Add uniform CDF blending to the polling strategy. When poll budget (k) is high, use targeted CDF from historical observations. As k decreases, blend towards uniform distribution to spread remaining polls evenly across the interval.
todos:
  - id: add-constants
    content: Add UNIFORM_BLEND_K_HIGH/K_LOW constants to CDFPollingStrategy
    status: pending
  - id: weight-method
    content: Add _compute_blend_weight() method
    status: pending
    dependencies:
      - add-constants
  - id: blend-cdfs
    content: Add _blend_cdfs() method to combine targeted and uniform CDFs
    status: pending
    dependencies:
      - add-constants
  - id: update-signatures
    content: Add reset_seconds param to update_budget() and _compute_poll_schedule()
    status: pending
    dependencies:
      - blend-cdfs
  - id: integrate-blending
    content: Modify _compute_poll_schedule() to build uniform CDF and blend
    status: pending
    dependencies:
      - weight-method
      - update-signatures
  - id: update-smart-polling
    content: Update SmartPollingManager.update_budget() to pass reset_seconds
    status: pending
    dependencies:
      - update-signatures
  - id: update-tests
    content: Update tests for new signatures and add blend behavior tests
    status: pending
    dependencies:
      - integrate-blending
      - update-smart-polling
---

# CDF Uniform Blending Implementation

Blend targeted CDF (from historical observations) with uniform CDF (synthetic) based on remaining poll budget. Uses clamped linear interpolation: pure targeted at k>=30, pure uniform at k<=10, linear blend in between.

## Algorithm

```
F_blended(t) = w × F_targeted(t) + (1-w) × F_uniform(t)

where:
  w = clamp((k - 10) / (30 - 10), 0, 1)

  # Synthetic observation for uniform CDF:
  uniform_start = elapsed (current time from interval start)
  uniform_end = elapsed + reset_seconds (when API quota resets)

  F_uniform(t) = (t - uniform_start) / (uniform_end - uniform_start)
```

The synthetic observation `[elapsed, elapsed + reset_seconds]` represents "confirmed price could arrive uniformly at any point from now until quota resets". This naturally spreads polls across the remaining quota window.

## Changes to [`cdf_polling.py`](custom_components/amber_express/cdf_polling.py)

1. **Add constants** for blend thresholds:

   - `UNIFORM_BLEND_K_HIGH = 30`
   - `UNIFORM_BLEND_K_LOW = 10`

2. **Add weight calculation method**:
   ```python
   def _compute_blend_weight(self, k: int) -> float:
       """Compute weight for blending targeted vs uniform CDF."""
       if k >= self.UNIFORM_BLEND_K_HIGH:
           return 1.0
       if k <= self.UNIFORM_BLEND_K_LOW:
           return 0.0
       return (k - self.UNIFORM_BLEND_K_LOW) / (self.UNIFORM_BLEND_K_HIGH - self.UNIFORM_BLEND_K_LOW)
   ```

3. **Modify `update_budget()` signature** to accept reset_seconds:
   ```python
   def update_budget(self, polls_per_interval: int, elapsed_seconds: float, reset_seconds: int) -> None:
   ```

4. **Modify `_compute_poll_schedule()` signature** to accept reset_seconds:
   ```python
   def _compute_poll_schedule(
       self,
       condition_on_elapsed: float | None = None,
       reset_seconds: int | None = None,
   ) -> None:
   ```

5. **Build uniform CDF** using the synthetic observation:

   - `uniform_start = condition_on_elapsed` (or 0 if unconditional)
   - `uniform_end = condition_on_elapsed + reset_seconds`
   - Creates observation `[uniform_start, uniform_end]`

6. **Add `_blend_cdfs()` method** to combine targeted and uniform CDFs:

   - Merge time points from both CDFs
   - At each time point, compute `w × F_targeted(t) + (1-w) × F_uniform(t)`
   - Return blended CDF for inverse sampling

## Changes to [`smart_polling.py`](custom_components/amber_express/smart_polling.py)

1. **Pass reset_seconds** to `CDFPollingStrategy.update_budget()`:
   ```python
   def update_budget(self, rate_limit_info: RateLimitInfo) -> None:
       # ...existing code...
       self._cdf_strategy.update_budget(
           polls_per_interval,
           elapsed,
           rate_limit_info["reset_seconds"],
       )
   ```


## Testing

Update existing tests in `tests/test_cdf_polling.py`:

- Update `update_budget()` calls to pass `reset_seconds` parameter
- Add tests for `_compute_blend_weight()`: verify clamped linear behavior at k=10, k=20, k=30
- Add tests verifying poll schedule stretches towards uniform as k decreases:
  - k=30: polls clustered around historical observation times
  - k=10: polls evenly spread from elapsed to reset time
- Add tests for edge cases (k=0, k > 30)

---
name: CDF Uniform Blending
overview: Add uniform CDF blending to the polling strategy. When poll budget (k) is high, use targeted CDF from historical observations. As k decreases, blend towards uniform distribution to spread remaining polls evenly across the interval.
todos:
  - id: add-constants
    content: Add UNIFORM_BLEND_K_HIGH/K_LOW constants to CDFPollingStrategy
    status: pending
  - id: interval-length
    content: Add interval_seconds parameter to CDFPollingStrategy constructor
    status: pending
    dependencies:
      - add-constants
  - id: weight-method
    content: Add _compute_blend_weight() method
    status: pending
    dependencies:
      - add-constants
  - id: uniform-cdf
    content: Add _build_uniform_cdf() method
    status: pending
    dependencies:
      - interval-length
  - id: blend-cdfs
    content: Add _blend_cdfs() method to combine CDFs at common time points
    status: pending
    dependencies:
      - uniform-cdf
  - id: integrate-blending
    content: Modify _compute_poll_schedule() to use blended CDF
    status: pending
    dependencies:
      - weight-method
      - blend-cdfs
  - id: update-smart-polling
    content: Update SmartPollingManager to pass interval_seconds
    status: pending
    dependencies:
      - interval-length
  - id: update-tests
    content: Update tests for new constructor signature and add blend tests
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
  F_uniform(t) = (t - t_start) / (t_end - t_start)
```

## Changes to [`cdf_polling.py`](custom_components/amber_express/cdf_polling.py)

1. **Add constants** for blend thresholds:

   - `UNIFORM_BLEND_K_HIGH = 30`
   - `UNIFORM_BLEND_K_LOW = 10`

2. **Store interval length** in constructor (needed to compute uniform CDF endpoint):

   - Add `interval_seconds: int` parameter to `__init__`
   - Store as `self._interval_seconds`

3. **Add weight calculation method**:
   ```python
   def _compute_blend_weight(self, k: int) -> float:
       """Compute weight for blending targeted vs uniform CDF."""
       if k >= self.UNIFORM_BLEND_K_HIGH:
           return 1.0
       if k <= self.UNIFORM_BLEND_K_LOW:
           return 0.0
       return (k - self.UNIFORM_BLEND_K_LOW) / (self.UNIFORM_BLEND_K_HIGH - self.UNIFORM_BLEND_K_LOW)
   ```

4. **Modify `_compute_poll_schedule()`** to blend CDFs:

   - Compute weight from current k
   - If w < 1.0, build uniform CDF from `condition_on_elapsed` (or 0) to `interval_seconds`
   - Create blended CDF: `F_blended(t) = w × F_targeted(t) + (1-w) × F_uniform(t)`
   - Sample poll times from blended CDF

5. **Add `_build_uniform_cdf()` method**:
   ```python
   def _build_uniform_cdf(self, start: float, end: float) -> list[tuple[float, float]]:
       """Build uniform CDF from start to end time."""
       return [(start, 0.0), (end, 1.0)]
   ```

6. **Add `_blend_cdfs()` method** to combine targeted and uniform CDFs at common time points.

## Changes to [`smart_polling.py`](custom_components/amber_express/smart_polling.py)

1. **Pass interval length** to `CDFPollingStrategy` constructor:
   ```python
   self._cdf_strategy = CDFPollingStrategy(
       observations,
       interval_seconds=interval_length * 60,
   )
   ```


## Testing

Update existing tests in `tests/test_cdf_polling.py` to:

- Pass `interval_seconds` to constructor
- Add tests for blend weight calculation
- Add tests verifying poll schedule stretches out as k decreases
- Add tests for edge cases (k=0, k very high)

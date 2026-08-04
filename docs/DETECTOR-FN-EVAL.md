# Measuring the detector's false-negative rate

*The one failure mode the conscience gate cannot save you from — and how to put a number on it.*

## Why this exists

The perception gate acts on the labels the detector **emits**. It is fail-closed
on anything it doesn't recognize, so a *misclassified* subject is handled safely.
But if the detector emits **no label at all** for a person who is present, the
gate never sees a human, nothing is refused, and the frame is stored and reaches
the reasoner. That is a *detector* false negative — upstream of the conscience,
and outside what any label→class rule can fix.

So the conscience layer's honesty depends on knowing this number: **how often
does the detector miss a person who is actually there?** This doc is the protocol
for measuring it. The harness is `obc_conscience::detector_eval`; the runner is
`oh-ben-claw eval-detector`.

## What you're measuring

For each **consent class** (chiefly `human`), over a set of frames where you know
the ground truth:

- **miss rate** = misses ÷ (frames where the class was truly present) = `1 − recall`.
- **95% upper bound** on that miss rate (Wilson). This is the headline number.

The point estimate lies; the bound doesn't. "0 misses in 20 frames" is a 0% point
estimate but a ~16% upper bound — meaning the true miss rate could still be as
high as one in six, you just haven't collected enough frames to rule it out. Plan
against the bound, not the point estimate.

## Collecting the eval set

You need frames where a **human** has said what was really present, paired with
what the **detector** reported for those same frames. The safety-critical subset
is frames that genuinely contain a person.

1. **Sample real frames from the deployment.** Pull a batch of frames the cameras
   actually captured — ideally spanning the conditions that break detectors: dusk
   and night, rain/snow, long range, partial occlusion (a person behind brush, in
   a vehicle, only a limb visible), odd poses (crouching, prone), and heavy motion
   blur. A detector's misses cluster in exactly these conditions, so an eval set of
   only clean daylight frames will report a miss rate far lower than reality.
2. **Deliberately over-sample person-present frames.** The bound shrinks with the
   number of *present* frames, not total frames. Aim for **≥ 100 frames that
   contain a person** for a usable human bound (100 present with 0 misses → ~3.6%
   upper bound; 30 → ~11%; fewer than ~30 and the harness prints a "too small"
   warning). Wildlife-only and empty frames are fine to include but don't tighten
   the human number.
3. **Annotate ground truth by hand.** For each frame, record the classes actually
   present, in the detector's/annotator's label vocabulary (e.g. `person`, `deer`).
   Do this **without looking at the detector output** so the labels are independent.
4. **Capture the detector output for the same frames.** Record what the detector
   emitted per frame (its raw labels). An empty list is the important case — it's
   a total miss.

### File format

A JSON array; one object per frame. `truth` is what a human says was present;
`detected` is what the detector emitted. `frame_id` is optional (traceability).

```json
[
  {"frame_id": "cam1-0003", "truth": ["person"], "detected": []},
  {"frame_id": "cam1-0004", "truth": ["person", "deer"], "detected": ["deer"]},
  {"frame_id": "cam1-0005", "truth": ["deer"], "detected": ["deer"]}
]
```

A worked sample lives at `crates/obc-conscience/examples/sample-eval-frames.json`
in the Oh-Ben-Claw repo.

## Running it

```
oh-ben-claw eval-detector --frames path/to/frames.json
```

Both `truth` and `detected` labels are classified onto consent classes using the
deployment's own `[conscience.classifier]` config — so the measurement matches
exactly what the live gate would do with those same labels. If your detector uses
a species taxonomy, add those labels to `[conscience.classifier.labels]` first, or
the harness will treat unrecognized *truth* labels as a data problem (it excludes
and reports them rather than inventing a class) and unrecognized *detected* labels
as covering the restricted class (mirroring the gate's fail-closed behavior).

### Reading the output

```
Detector false-negative report (10 frames)
'human' miss rate: 33.3% (2 missed of 6 present); 95% upper bound 70.0%.  ⚠ sample too small to conclude — widen the eval set.
  class        present  missed     FP missrate    upper95
  human              6       2      1    33.3%      70.0%
  wildlife           4       1      0    25.0%      69.9%
```

- Read the **`human` upper95** as your privacy exposure: with this eval set the
  human miss rate could be as high as that bound.
- `FP` (false positives — detector cried "person" when none was present) is *not*
  a safety failure on a default-deny body; it only over-refuses. It's reported so
  a noisy detector is visible.
- The **⚠ warning** means the sample is too small to conclude. Collect more
  person-present frames and re-run.

## Interpreting the number

There is no single "acceptable" miss rate — it depends on what a missed capture
costs in the deployment and what compensating controls exist (e.g. review state,
retention limits, physical siting away from neighbors). What this harness gives
you is an **honest, defensible number with its uncertainty attached**, so the
decision is made on evidence instead of on the comfortable point estimate. Re-run
whenever the detector model, camera placement, or environment changes — the miss
rate is a property of all three, not of the model alone.

## What this does *not* measure

- **Classifier errors** (label→class mistakes). Those are the gate's own layer and
  are handled fail-closed; this is only about the detector emitting nothing.
- **A live number, until you feed it a real eval set.** The harness and its tests
  prove the method on synthetic frames; the field number requires the annotated
  set above. Until then, treat the human miss rate as *unmeasured*, not *low*.

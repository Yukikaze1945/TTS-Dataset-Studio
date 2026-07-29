# Audio Enhancement V1

## Goal

Add three non-destructive audio cleanup paths to the existing selection workflow:

- **Quick denoise** — DPDFNet `dpdfnet8_48khz_hr`
- **Remove BGM** — BS-RoFormer through `python-audio-separator`
- **Studio repair (experimental)** — StuPASE

The source media is never modified. Every successful result is placed on a
dedicated **Enhancement** generated-audio track at the selected region's start
time. Source, IndexTTS output, and enhancement output remain independently
muteable/soloable for A/B listening.

## Interaction

The contextual action bar shows one `Process audio` menu when an export region
is selected. The menu contains the three workflows above. It is hidden for
subtitle-only and generated-clip selections.

For one or more selected regions:

1. Extract each region from the source as mono PCM WAV without project gain,
   normalization, or fades.
2. Run the selected external engine in a background task.
3. Validate and probe the produced file.
4. Copy it atomically into the project sidecar/cache.
5. Insert or replace the matching clip on the Enhancement track.

Completed clips are retained if a later batch item fails or the user cancels.
An engine failure never changes the source media or the IndexTTS track.

## Data model

`GeneratedAudioTrack` gains a backwards-compatible `kind` field:

- `generated` — IndexTTS output
- `enhancement` — denoise/separation/repair output

`MediaAsset.generated_track` continues to return the IndexTTS track.
`MediaAsset.enhancement_track` returns (and lazily creates) the enhancement
track. Timeline hit testing, collision detection, clip editing, selection,
project save/load, waveform generation, and monitor-cache mixing operate over
all generated tracks. Collisions are checked only within the edited track.

## Engine isolation

Large model stacks are optional external environments and are not bundled in
the GitHub download:

- DPDFNet runs with its own small CPU/ONNX Python environment.
- BS-RoFormer runs with an `audio-separator` CUDA environment.
- StuPASE runs from its official checkout and environment.

Paths and parameters live under Settings → AI engines → Audio processing.
Environment variables and the app data engine directory are detected before
manual paths. No machine-specific drive path is stored in source code.

## Playback

The existing sparse monitor-cache builder mixes all generated tracks into one
FLAC while respecting per-track Mute/Solo state in the main window. The source
monitor remains separate, so source-only, enhancement-only, and mixed listening
are all possible. Any track layout change invalidates and atomically rebuilds
the cache.

## Error handling

- Missing engine environments produce an actionable settings notification.
- A missing output, invalid WAV, non-zero process exit, or cancellation does not
  insert a clip.
- Temporary files are removed after each batch.
- StuPASE is labeled experimental because it is a 16 kHz generative repair
  model and can change speaker detail.
- Output files are not overwritten; replacement happens in the project model
  only after the new file is complete.

## Verification

Unit tests cover settings detection/round trips, legacy project loading, track
lookup, multi-track duration/collision behavior, monitor-cache input selection,
command construction, partial-success/cancellation semantics, and contextual
action visibility. Integration checks run each installed engine on a short WAV,
probe the result, and verify insertion into the Enhancement track.

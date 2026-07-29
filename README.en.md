# TTS Dataset Studio

English · [简体中文](README.md)

TTS Dataset Studio is a lightweight Windows workstation for extracting TTS-ready audio
clips and editing their subtitles. It combines media import, waveform preview, multiple
subtitle tracks, non-destructive regions, gain control, and FFmpeg export in one interface.

> Current version: `v0.2.0-alpha.1`. This is a prerelease; save projects before important work.

## Studio Fluent interface

- Empty projects show one import entry point and a three-step guide.
- Imported media opens a single workspace with library, preview, timeline, and contextual actions.
- Clip properties appear only when requested; encoding, AI engines, caches, and tool paths stay in Settings.
- Dark, light, and Windows-system themes are supported, with automatic library collapse in narrow windows.

## Highlights

- Drag in media, associate neighboring subtitle files, and import embedded text subtitle tracks.
- Embedded mpv video preview, audio waveform preview, and a zoomable multi-track timeline.
- Editable subtitle and export-region boundaries with multi-select, snapping, undo, and redo.
- WAV, FLAC, and MP3 export with sample-rate, channel, bit-depth, gain, fade, and naming options.
- Subtitle-based filenames and optional matching UTF-8 TXT files.
- Frame stepping, clean still-frame export, and an optional Windows context-menu installer.
- Optional MOSS-Transcribe-Diarize integration for timestamped, speaker-aware transcription.
- Optional DPDFNet denoising, BS-RoFormer BGM removal, and experimental StuPASE repair.

## Install

For most users, download `TTS-Dataset-Studio-*-setup-x64.exe` from
[Releases](https://github.com/Yukikaze1945/TTS-Dataset-Studio/releases). The installer can add
Start Menu, desktop, and media-file context-menu entries.

Alternatively, download `TTS-Dataset-Studio-*-windows-x64.zip` from
[Releases](https://github.com/Yukikaze1945/TTS-Dataset-Studio/releases), extract it, and run
`TTS Dataset Studio.exe`. FFmpeg, ffprobe, and mpv are included.

To install Start Menu and Windows 11 context-menu entries:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install.ps1
```

## Run from source

Requirements: Windows 10/11 x64, Python 3.11–3.14,
[uv](https://docs.astral.sh/uv/), FFmpeg/ffprobe on `PATH`, and optionally mpv.

```powershell
git clone https://github.com/Yukikaze1945/TTS-Dataset-Studio.git
cd TTS-Dataset-Studio
uv sync --extra dev --frozen
uv run tts-dataset-studio
```

## Shortcuts

| Key | Action |
| --- | --- |
| Space | Play/pause |
| I / O | Set in/out points |
| Enter | Play the current subtitle or region |
| E | Export audible tracks with the active preset (respects Mute/Solo) |
| X | Delete selected export regions |
| D / F | Previous/next video frame |
| C | Save a clean source-video still |
| G | Generate IndexTTS2 speech for the selected regions |
| Ctrl+S | Save project |
| Ctrl+Z / Ctrl+Shift+Z | Undo/redo |
| Alt+Wheel | Zoom timeline |
| ? | Show shortcut help |

## Optional MOSS ASR

MOSS, PyTorch, and model weights are not distributed with this project. Install
[MOSS-Transcribe-Diarize](https://github.com/OpenMOSS/MOSS-Transcribe-Diarize), then either:

1. Set `MOSS_TRANSCRIBE_DIARIZE_HOME`.
2. Place it at `moss-asr\MOSS-Transcribe-Diarize` on any Windows drive.
3. Select its directory, Python environment, and model under Settings → AI Engines → ASR.

## Optional IndexTTS2 speech engine

IndexTTS2, PyTorch, CUDA, and model weights are not distributed with the repository or portable
build. The application discovers an external installation through `INDEX_TTS_HOME`, common
`index-tts` locations on Windows drives, or the directory configured under Advanced Settings →
Speech Engine. A typical installation contains `.venv\Scripts\python.exe`,
`indextts\infer_v2.py`, and `checkpoints\config.yaml`.

Select an export subtitle track and one or more regions, then press `G`; the engine loads on
demand. Each region's untreated source audio is used as its own reference. Results are inserted into
the editable **AI Generated** track, which supports moving, non-destructive trimming, deletion,
undo/redo, and Mute/Solo synchronized monitoring. Saved projects store generated WAV files under
the matching `.ttds.assets/generated` directory.

Run the optional local GPU smoke test with:

```powershell
.\scripts\index-tts-smoke.ps1 -IndexTtsRoot X:\index-tts
```

## Optional audio enhancement engines

Select one or more regions and open **Process audio** in the contextual action bar:

- **Quick denoise** uses the 48 kHz
  [DPDFNet](https://github.com/ceva-ip/DPDFNet)
  `dpdfnet8_48khz_hr` CPU/ONNX model.
- **Remove BGM** uses BS-RoFormer through
  [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator)
  with CUDA.
- **Studio repair (experimental)** uses
  [StuPASE](https://github.com/cisco-open/pase) for combined noise and reverb repair.

Results are added to a separate **Enhancement** track; source media is never overwritten.
Source, generated, and enhancement tracks have independent Mute/Solo controls for A/B monitoring.
The optional environments and model weights are not bundled. Configure them under Settings →
AI Engines → Audio Processing, or use `DPDFNET_PYTHON`, `AUDIO_SEPARATOR_PYTHON`, and
`STUPASE_HOME`. StuPASE is currently a 16 kHz generative model and can change speaker detail,
so compare its result with the source before using it for training.

## Development

```powershell
uv sync --extra dev --frozen
uv run ruff check src tests
uv run pytest
.\scripts\fetch-runtime.ps1
.\scripts\build-release.ps1 -Version 0.2.0-alpha.1
```

## Known limitations

- Windows 10/11 x64 only.
- One source asset per timeline; no multi-clip editing, transitions, or final video export.
- MOSS ASR requires a separately installed Python/CUDA/model environment.
- IndexTTS2 requires a separately installed Python/CUDA/model environment; only the protocol
  worker is included in portable builds.
- Audio enhancement engines require separate Python/model environments and may download several
  gigabytes on first use.
- Image-based embedded subtitles such as PGS, VobSub, and DVB require OCR and are not imported.
- Speaker-separation pipelines, quality scoring, and framework-specific metadata are outside V1.

## License

Application source is [MIT licensed](LICENSE). Bundled Qt/PySide6, FFmpeg, mpv, and Python
dependencies retain their respective licenses; see [Third-party notices](THIRD_PARTY_NOTICES.md).

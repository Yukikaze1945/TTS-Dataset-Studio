# Third-party notices

TTS Dataset Studio source is MIT licensed. Windows release archives also distribute unmodified
third-party components as separate executables or dynamically linked libraries:

- **Qt for Python / PySide6 6.11.x** — LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only.
- **Qt 6 libraries** — principally LGPL-3.0-only/GPL; exact notices are copied from the installed
  PySide6 wheel into each release archive.
- **FFmpeg / ffprobe 8.0.1 full build by gyan.dev** — GPLv3. The pinned archive, checksum,
  build information, and corresponding FFmpeg source tag are recorded in
  `packaging/runtime-dependencies.json`.
- **mpv 0.41.0 Windows x64 CI build** — LGPL-2.1-or-later and GPL-2.0-or-later components.
  The unmodified archive comes from the mpv GitHub release and is checksum-verified.
- **platformdirs** — MIT.

FFmpeg, ffprobe, and mpv are launched as separate processes. Their license texts, build readmes,
and source links are placed under `licenses/` in the portable archive. Python wheel license
directories are collected during release packaging.

Project maintainers should not replace these pinned runtime files without updating the manifest,
checksums, notices, and corresponding-source references.

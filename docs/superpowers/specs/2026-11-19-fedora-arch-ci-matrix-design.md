# Fedora and Arch Linux CI test runs — design

## Intent
Verify the test suites of `decker` and `decker-plugins` on Fedora and Arch Linux (todo: "Additional Matrix Tests"), so
the Linux tier-1/2 columns in `docs/platform-support.md` can move from "Not verified" to "CI".

## Goals / non-goals
- Goals: run the existing pytest suites (decker: `tests`; plugins: tool tests plus each plugin's tests) on Fedora and Arch.
- Non-goals: no pylint/mypy/format runs on the distros (distro-independent, Ubuntu job covers them); no hardware tests;
  no new test code; no Debian/other distros.

## Approaches
1. **Container jobs on the Ubuntu runner** (`container: fedora:latest` / `archlinux:latest`), each installing its own
   system packages. Chosen: GitHub has no native Fedora/Arch runners; this is the standard route and keeps the real
   distro userland (libs, fontconfig, Python).
2. Self-hosted runners / VMs: more faithful, but infrastructure to maintain. Rejected.
3. Chosen for Python: the distro's own Python 3.14 where available; fall back to `uv python install 3.14` only if a
   distro lacks it (builder's call).

## Design
- `decker/.github/workflows/ci.yml`: add a `test-distro` job, matrix `distro: [fedora, arch]` with image mapping, QT
  offscreen env as in `test`. Steps: install system packages (hidapi, cairo, Qt offscreen deps: EGL/GL/xkbcommon,
  fontconfig, dbus, git, uv), checkout, project setup (`poetry install` via the same commands as `setup-poetry`, since
  that action uses `setup-python`, which is unreliable in non-Debian containers), run the same pytest command, upload
  reports as `test-reports-<distro>`.
- `decker-plugins/.github/workflows/ci.yml`: same matrix on the `test` job's steps (`uv sync --locked`, tool tests,
  plugin tests loop), packages: cairo, uv, git, fontconfig.
- **Fedora is blocking**; **Arch is non-blocking** (`continue-on-error: true` on the arch matrix leg, so failures show
  as a warning-style failed leg without failing the run). Arch is excluded from the `build` job's `needs` gating.
- Docs: update `docs/platform-support.md` (and the plugins repo table) from "Not verified" to "CI" only for rows the
  green runs actually cover, citing the run id; note Arch is advisory because it is a rolling release.

## Left to the builder
Exact package names per distro, Python 3.14 provisioning, whether to pin Fedora to a release instead of `latest`.

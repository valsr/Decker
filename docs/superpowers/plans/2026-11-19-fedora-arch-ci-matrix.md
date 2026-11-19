# Fedora and Arch CI Test Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the `decker` and `decker-plugins` test suites on Fedora and Arch Linux in CI, with Arch advisory only.

**Architecture:** A matrix job per repo runs on `ubuntu-latest` inside `fedora:latest` / `archlinux:latest` containers. Each installs its system packages and the project environment itself, then runs the same pytest commands as the existing `test` job.

**Tech Stack:** GitHub Actions, Docker container jobs, dnf/pacman, uv, Poetry, pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-fedora-arch-ci-matrix-design.md`

## Global Constraints

- Only tests run on the distros: no pylint, mypy, format or build steps.
- Fedora blocks; Arch uses `continue-on-error: true` and is not in any job's `needs`.
- Python is `>=3.14` (decker `^3.14`, plugins `>=3.14`); `QT_QPA_PLATFORM: offscreen`.
- Do not use `actions/setup-python` or the `setup-poetry` action inside containers.
- Existing `test`, `build` and `lint-and-package` jobs stay unchanged.
- Docs rows move to `CI` only for what green runs cover, citing the run id.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- Python 3.14 missing from a distro's repos: the job must still get 3.14 (fall back to `uv python install 3.14`), not fail on an unrelated version error.
- `actions/checkout` and `upload-artifact` in a bare container: need `git` and node-compatible libc; install `git` first.
- Arch leg failing: the workflow run must stay green and the leg must be visibly marked failed.
- Plugin test loop: one failing plugin must not stop the others (keep the existing `status=1` pattern).
- Stale Arch package DB: `pacman -Syu` before installs, or installs 404.

---

### Task 1: decker `test-distro` job

**Files:**
- Modify: `.github/workflows/ci.yml` (add job after `test`; `build.needs` unchanged)

**Interfaces:**
- Produces: job id `test-distro`, matrix key `distro` (`fedora` | `arch`), artifacts `test-reports-fedora`, `test-reports-arch`.

- [ ] **Step 1: Add the job**

  `name: test (${{ matrix.distro }})`, `runs-on: ubuntu-latest`, `container: ${{ matrix.image }}`,
  `continue-on-error: ${{ matrix.experimental }}`, `strategy.fail-fast: false`, matrix
  `include: [{distro: fedora, image: "fedora:latest", experimental: false}, {distro: arch, image: "archlinux:latest", experimental: true}]`,
  `env: QT_QPA_PLATFORM: offscreen`.

- [ ] **Step 2: Install system packages (one step per distro, `if: matrix.distro == ...`)**

  Fedora: `dnf install -y git python3.14 python3-pip hidapi cairo mesa-libEGL mesa-libGL libxkbcommon fontconfig dbus-libs uv`.
  Arch: `pacman -Syu --noconfirm git python python-pip hidapi cairo libglvnd libxkbcommon fontconfig dbus uv`.
  Builder verifies the exact names in the containers; if `python3.14` is absent on Fedora, drop it and use
  `uv python install 3.14` plus `uv venv`-based Poetry install.

- [ ] **Step 3: Checkout, install Poetry and the project, run tests**

  `actions/checkout@v7`; `python3 -m pip install poetry` (use `--break-system-packages` on Arch if pip refuses);
  `poetry install`; `poetry run pytest -rs --junitxml=report.xml --cov-report xml:coverage.xml --cov=decker tests`.
  Upload `report.xml` and `coverage.xml` as `test-reports-${{ matrix.distro }}` with `if: always()`.

- [ ] **Step 4: Lint the workflow**

  Run: `actionlint .github/workflows/ci.yml` (or `uvx actionlint-py`). Expected: no errors.

- [ ] **Step 5: Verify in CI**

  Push a branch, open a PR, wait for `test (fedora)` and `test (arch)`. Expected: Fedora green; Arch green or failed
  without failing the overall run (confirm the PR's required checks do not list `test (arch)`).

- [ ] **Step 6: Commit** — `ci: run tests on Fedora and Arch Linux containers`

### Task 2: decker-plugins distro legs

**Files:**
- Modify: `../decker-plugins/.github/workflows/ci.yml` (add `test-distro` job; existing `test` unchanged)

**Interfaces:**
- Consumes: Task 1's matrix layout (same `include` entries, same `experimental` semantics).

- [ ] **Step 1: Add the job** with the same matrix, container and `continue-on-error` as Task 1, `permissions: contents: read`, `QT_QPA_PLATFORM: offscreen`.

- [ ] **Step 2: Install packages**: `git`, `uv`, `cairo`, `fontconfig`, plus Python 3.14 as in Task 1 (`uv` can provision it, so `uv sync --locked` is enough if the distro lacks it).

- [ ] **Step 3: Run `uv sync --locked`, `uv run pytest -rs tests`, and the existing per-plugin loop** (copy the `status=1` loop from the `test` job verbatim, `shell: bash`; install `bash` is already present on both images).

- [ ] **Step 4: Lint** with `actionlint`, then push a branch and confirm both legs as in Task 1 Step 5.

- [ ] **Step 5: Commit** in the plugins repo — `ci: run tests on Fedora and Arch Linux containers`

### Task 3: Platform docs

**Files:**
- Modify: `docs/platform-support.md` (Ubuntu/Debian/Fedora/GNOME and Linux (other) columns as appropriate; the paragraph at line 47-49)
- Modify: plugins repo platform table (find with `grep -rn "Not verified" ../decker-plugins/docs ../decker-plugins/README.md`)

- [ ] **Step 1:** After Tasks 1-2 are green, set to `CI` only the rows whose tests ran on Fedora (and Arch where it passed), with a footnote citing the run ids and stating that Arch is advisory because it is a rolling release and Qt/GUI offscreen only, no hardware.
- [ ] **Step 2:** Update the "CI also runs the suite on Ubuntu" sentence to mention Fedora and Arch.
- [ ] **Step 3:** Mark "Additional Matrix Tests" done in `/work/decker/admin/todo.user.md`.
- [ ] **Step 4: Commit** — `docs: record Fedora and Arch CI coverage`

## Self-review

Spec coverage: both repos (Tasks 1-2), Fedora blocking and Arch advisory (Global Constraints, Task 1 Step 1), tests-only (constraints), docs (Task 3), builder calls on packages/Python (Task 1 Step 2).

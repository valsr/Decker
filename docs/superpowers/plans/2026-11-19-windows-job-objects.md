# Windows Job Objects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On Windows every plugin process tree lives in a Job Object with `KILL_ON_JOB_CLOSE`, so helpers die when their leader exits, is killed, or the server dies.

**Architecture:** A private `ctypes` module (`decker/common/_winjob.py`) wraps the job calls; `decker.common.processes` gains `adopt(proc)` and makes `kill_tree` terminate the job when one exists. The two plugin `Popen` call sites call `adopt` once. POSIX is untouched.

**Tech Stack:** Python 3.14 `ctypes` (kernel32), psutil, pytest + assertpy, GitHub Actions (Windows runner).

**Spec:** `docs/superpowers/specs/2026-11-19-windows-job-objects-design.md`.

## Global Constraints

- Job per plugin process: created with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (extended limit information class), the `Popen` process assigned right after spawn. The registry is a `weakref.WeakKeyDictionary[subprocess.Popen[Any], <job>]`; a `weakref.finalize` on the Popen closes the handle (closing kills what is left in the job).
- `adopt(proc: subprocess.Popen[Any]) -> None` never raises and is a no-op on POSIX; on failure it logs once at debug level and the psutil walk stays the only mechanism.
- `kill_tree(proc)`: with a job, `TerminateJobObject` then close the handle, even when the leader already exited (do NOT apply the Windows "leader exited, leave it alone" early return in that case); without a job, behaviour is exactly today's. `terminate_tree` is unchanged. Signatures of `group_popen_kwargs`, `terminate_tree`, `kill_tree`, `rss_bytes` do not change.
- Ruling (deviation from the spec): no separate `release` function. The plugin supervisor's `_watch` already calls `_kill_group()` (which is `kill_tree`) after the leader exits, and that now terminates the job and closes the handle, so helpers die with their leader; a `release` with no caller would be dead code.
- Platform branches use `if sys.platform == "win32":` so `poetry run mypy --platform win32 .` and `--platform darwin .` both check them; the Windows-only `ctypes` code must also pass on Linux mypy.
- Tests that need Windows use the registered `windows_only` marker with a reason naming the feature and its row in `docs/platform-support.md`; no silent skips. Tests must assert the job is really in effect (not pass vacuously when job creation failed).
- Project rules: annotate everything (tests too), methods < 50 lines, max 5 args, docstrings on public items only, black 120. Gates: `poe format`, `poe mypy` (+ both `--platform` runs), `poe pylint` (>= 9.0), `poe test` (coverage >= 85%; Windows-only lines may need `# pragma: no cover` or a platform exclusion, builder's choice, state it in the report). Tests mirror `src/` under `tests/`, real processes over mocks.
- Every commit message: subject, a BLANK LINE, then the trailers `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FG9NRj5PgFFP8CrgR6aMLZ`.
- The maintainer approved pushing the work branch `feat/windows-job-objects` to GitHub to verify on the Windows and macOS runners (`gh workflow run ci.yml --ref <branch>`, `gh run list/watch/view`); no PR until the matrix is green. Use HTTPS with the gh token; never print the token.

## Review Focus

- A helper whose leader already exited is killed by `kill_tree` on Windows (the case the psutil walk cannot reach) (Tasks 1, 2).
- Job creation or assignment failing (nested-job refusal, access denied) never raises and falls back to the psutil walk (Task 1).
- POSIX behaviour is unchanged: `adopt` is a no-op and `kill_tree`/`terminate_tree` still use `killpg` (Task 1).
- The handle is not leaked and an unrelated process outside the job is never touched (Task 1).
- The real plugin supervisor path (executable plugin with a helper) leaves nothing behind after the leader exits (Task 2).

---

### Task 1: Job object module and `adopt` / `kill_tree`

**Files:**
- Create: `src/decker/common/_winjob.py`
- Modify: `src/decker/common/processes.py`
- Modify: `tests/common/test_processes.py`

**Interfaces:**
- Produces: `processes.adopt(proc: subprocess.Popen[Any]) -> None`; `kill_tree` job path (as in Global Constraints). `_winjob` offers `create_job() -> int | None` (handle or None), `assign(handle: int, pid: int) -> bool`, `terminate(handle: int) -> None`, `close(handle: int) -> None`; all swallow `OSError`, return a falsy result on failure, and are only called when `sys.platform == "win32"`.

- [ ] **Step 1: Write failing tests** in `tests/common/test_processes.py` (reuse `_spawn`, `_PARENT`, `_read_pid`, `_wait_gone`): cross-platform `test_adopt_is_harmless_for_any_process` and `test_kill_tree_after_adopt_on_an_exited_process_does_not_raise`; `test_adopt_failure_falls_back_to_the_psutil_walk` (monkeypatch `_winjob.create_job` to return None, then `kill_tree` of a live parent still kills parent and child; on POSIX the `killpg` path runs, so the test is meaningful on both); `windows_only`: `test_kill_tree_reaches_a_helper_after_the_leader_exited` (spawn `_PARENT` with `adopt`, read the helper pid, kill ONLY the leader with `proc.kill()`, wait for it, then `kill_tree(proc)`; helper must be gone; also assert before the final call that the helper is still alive, proving the job, not the leader's death, did it), `test_helper_dies_when_the_job_handle_closes` (adopt, then `del proc` plus `gc.collect()` is NOT acceptable as the only trigger; use the finalizer path via an explicit helper in `processes` only if the weak finalize can be driven deterministically, otherwise assert through `kill_tree`), `test_process_outside_the_job_survives_kill_tree`.
- [ ] **Step 2: Run** `poe test tests/common/test_processes.py` — expect FAIL (names missing).
- [ ] **Step 3: Implement** `_winjob` with `ctypes.windll.kernel32` structures (`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, info class `JobObjectExtendedLimitInformation = 9`, `AssignProcessToJobObject` using a handle from `OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, ...)` or the Popen `_handle`, builder's choice), and `processes.adopt` / the `kill_tree` job path with the registry and finalizer from Global Constraints.
- [ ] **Step 4: Run** `poe test tests/common` plus `poetry run mypy .`, `--platform win32 .`, `--platform darwin .` — expect PASS (Windows-only tests skip here with their reason).
- [ ] **Step 5: Commit** `feat: put Windows plugin processes in a kill-on-close job object`.

---

### Task 2: Wire the plugin call sites

**Files:**
- Modify: `src/decker/plugin/runtime/process.py` (`start`), `src/decker/plugin/environment.py` (`_run`)
- Modify (tests): the existing plugin runtime process test module (find it under `tests/plugin/runtime/`) and, if cheap, `tests/plugin/test_environment.py`

**Interfaces:**
- Consumes: `processes.adopt(proc)` from Task 1.

- [ ] **Step 1: Write failing tests**: `windows_only` `test_helper_is_killed_when_the_plugin_leader_exits` using the real plugin process class with a command whose leader starts a helper then exits (use `tests/portable.py` helpers for the launcher); assert the helper pid is gone after the exit callback fired and the helper was alive just before the leader exited. A cross-platform test that the process class still starts, stops and kills a normal child.
- [ ] **Step 2: Run** the module — expect the Windows test FAIL on Windows (skipped, so on Linux just confirm collection); note that RED evidence for the Windows case comes from the CI run in Task 4.
- [ ] **Step 3: Implement**: call `processes.adopt(proc)` immediately after each `Popen(...)` (runtime `start` and `environment._run`); no other change (`_watch` already ends with `_kill_group`).
- [ ] **Step 4: Run** `poe test tests/plugin`, three `mypy` runs, `poe pylint` — expect PASS.
- [ ] **Step 5: Commit** `feat: adopt plugin and build subprocesses into a job on Windows`.

---

### Task 3: Docs

**Files:**
- Modify: `docs/platform-support.md` (footnote 6 and the plugin runtime row), `DAEMON.md` (Platform notes), `CLAUDE.md` (plugins bullet and the `decker.common.processes` bullet)

- [ ] **Step 1:** Replace every statement that orphaned helpers are not cleaned up or that Job Objects are a not-implemented follow-up with the job-object behaviour (kill-on-close, helpers die with the leader and with the server, kill_tree reaches helpers of an exited leader, terminate stays a psutil walk); document the spawn-to-assign race and the silent fallback when a job cannot be created; mention the new `_winjob` module in the processes bullet. Leave Windows/macOS cells as they are until Task 4 supplies evidence.
- [ ] **Step 2: Commit** `docs: describe Windows job objects for plugin processes`.

---

### Task 4: Drive the matrix to green

**Files:** any file a failure needs; `docs/platform-support.md` for the final cells.

- [ ] **Step 1:** Run the local gates, push `feat/windows-job-objects`, run `gh workflow run ci.yml --ref feat/windows-job-objects`, read failures with `gh run view <id> --log-failed`.
- [ ] **Step 2:** Fix each failure at its cause (one cause per commit); `ctypes` structure or handle mistakes are expected on the Windows runner. Stop with BLOCKED if a failure needs a design decision or after 6 workflow runs. Confirm in the run log that the `windows_only` tests actually ran (not skipped) and passed.
- [ ] **Step 3:** When test x3, mypy (both platform runs), format, pylint and build are green, set the `docs/platform-support.md` cells to what the runs prove (the real job-object tests ran and passed on Windows) and commit `docs: record job object CI coverage`. Do not open a PR.

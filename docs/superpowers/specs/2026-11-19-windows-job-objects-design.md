# Windows Job Objects for plugin processes — design

Follow-up to `2026-11-18-windows-graceful-stop-design.md` (PR #43). Small change.

## Intent

On Windows a plugin's process tree is only stopped by a psutil walk that starts at the leader, and only while the leader is alive. When the leader exits or is hard-killed, helpers it started are orphaned (their parent pid may be recycled, so we leave them alone). POSIX does not have this problem because `os.killpg` reaches the whole group. A Windows Job Object with `KILL_ON_JOB_CLOSE` removes the class: every process in the job dies when the job is closed or terminated, whether or not the leader is still there.

## Goals

- Every plugin child (runtime and the uv/venv build subprocesses) is placed in its own job on Windows.
- When the plugin's leader exits, or the supervisor kills it, or the server itself dies (handles close), its helpers die.
- Same public surface for callers on every OS; POSIX behaviour unchanged.
- A real test on the Windows runner proves a helper dies after its leader is killed.

## Non-goals

- A job for the server child under the monitor (decided: plugins only).
- Closing the spawn-to-assign race (a helper started in the first milliseconds before assignment can escape; documented).
- Job-based memory limits, CPU limits, or UI restrictions.
- A soft stop through the job (a job has none; `terminate_tree` keeps the psutil walk).

## Approaches considered

- **A. `ctypes` job objects in `decker.common` (chosen).** No new dependency, about 80 lines, testable on the Windows runner (nested jobs are allowed on Windows 8+, and the runners already run inside a job).
- B. `pywin32`: cleaner calls, but a Windows-only dependency, stubs and markers for three API calls.
- C. A better psutil walk: cannot work once the leader has exited.

## Design

**New private module** `decker/common/_winjob.py` holds the `ctypes` code (`CreateJobObjectW`, `SetInformationJobObject` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, `AssignProcessToJobObject`, `TerminateJobObject`, `CloseHandle`); platform branches use `if sys.platform == "win32":` so `mypy --platform` checks both sides.

**Public API stays in `decker.common.processes`:**
- `adopt(proc: subprocess.Popen[Any]) -> None`: Windows creates a job, assigns the process, and remembers the handle in a `WeakKeyDictionary` keyed by the `Popen`; POSIX is a no-op. Never raises: if creation or assignment fails (access denied, an old non-nestable outer job), it logs once at debug level and the psutil walk stays the only mechanism.
- `kill_tree(proc)` terminates the job when there is one (reaches helpers of an exited leader), then closes it; falls back to the current psutil walk otherwise.
- `terminate_tree(proc)` is unchanged (soft/polite psutil walk).
- `release(proc: subprocess.Popen[Any]) -> None`: closes the job handle, which kills anything still in the job. The plugin supervisor calls it when the leader's watcher sees the process exit, so helpers die with their leader; `environment._run` already ends with `kill_tree`.

**Callers.** `plugin/runtime/process.py` calls `processes.adopt(proc)` right after `Popen`, and `release` in its exit watcher; `plugin/environment.py` calls `adopt` after `Popen`. No other call sites change.

**Server death.** The server process owns the job handles, so a hard-killed server closes them and the OS kills every plugin tree; no extra code.

**Tests.**
- `windows_only` (reason names the feature and its docs row): a leader spawns a helper that sleeps; after `adopt`, the leader is killed hard and the helper must be gone within a deadline; the same through `kill_tree`; `release` kills a live helper; a second process outside the job is untouched.
- Cross-platform: `adopt` and `release` are harmless no-ops on POSIX, `kill_tree` on an already-exited process never raises, a failing job creation (monkeypatched) falls back without raising.
- The supervisor test that stops a real plugin child keeps running on all OSes.

**Docs.** `docs/platform-support.md` footnote 6 and the plugin runtime row (orphan statement removed, the spawn race noted, cells `CI` only where the run proves it), `DAEMON.md` platform notes, `CLAUDE.md` (the Job Objects follow-up text and the `decker.common.processes` bullet).

## Left to the builder

Struct layouts and the exact `ctypes` signatures, where the job registry lives, how the helper in the test is built (portable launchers from `tests/portable.py`), coverage handling for the Windows-only lines.

## Risks

`ctypes` structure mistakes only show on the Windows runner (expect rounds there); a runner whose outer job forbids nesting would make `adopt` fall back silently, so the test asserts the job is actually in effect rather than passing vacuously.

## Calls I made (for review)

Module split with a private `_winjob.py`; a `WeakKeyDictionary` registry so existing `terminate_tree`/`kill_tree` signatures stay; closing the job when the leader exits (helpers die with the leader); branch `feat/windows-job-objects` created from `feat/windows-graceful-stop` (docs overlap with PR #43, rebase after it merges).

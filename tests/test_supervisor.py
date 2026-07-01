from director.supervisor import (
    HEALTHY_UPTIME_SECONDS,
    MAX_BACKOFF_SECONDS,
    MIN_BACKOFF_SECONDS,
    ManagedProcess,
    next_backoff,
)


def test_next_backoff_doubles_up_to_the_max():
    b = MIN_BACKOFF_SECONDS
    seen = []
    for _ in range(10):
        b = next_backoff(b)
        seen.append(b)
    assert seen[-1] == MAX_BACKOFF_SECONDS
    assert seen == sorted(seen)  # monotonically non-decreasing


class FakeProc:
    def __init__(self, pid=1234):
        self.pid = pid
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True


def make_process(tmp_path, monkeypatch, popen_results):
    """popen_results: list of FakeProc instances returned by successive
    subprocess.Popen calls, in order."""
    monkeypatch.setattr("director.supervisor.LOG_DIR", tmp_path)
    monkeypatch.setattr("director.supervisor.time.sleep", lambda seconds: None)
    calls = []
    results = iter(popen_results)

    def fake_popen(cmd, cwd, stdout, stderr):
        calls.append(cmd)
        return next(results)

    monkeypatch.setattr("director.supervisor.subprocess.Popen", fake_popen)
    return calls


def test_start_launches_the_module_and_writes_a_log_header(tmp_path, monkeypatch):
    proc = FakeProc()
    calls = make_process(tmp_path, monkeypatch, [proc])

    m = ManagedProcess("director.run_playout")
    m.start()

    assert m.proc is proc
    assert calls == [[__import__("sys").executable, "-m", "director.run_playout"]]
    assert m.log_path.exists()
    assert "starting director.run_playout" in m.log_path.read_text(encoding="utf-8")


def test_poll_and_maybe_restart_leaves_a_running_process_alone(tmp_path, monkeypatch):
    proc = FakeProc()
    make_process(tmp_path, monkeypatch, [proc])

    m = ManagedProcess("director.run_playout")
    m.start()
    original_backoff = m.backoff

    m.poll_and_maybe_restart()

    assert m.proc is proc  # not replaced
    assert m.backoff == original_backoff  # not yet "healthy" (no time has passed)


def test_poll_and_maybe_restart_resets_backoff_once_healthy(tmp_path, monkeypatch):
    proc = FakeProc()
    make_process(tmp_path, monkeypatch, [proc])

    m = ManagedProcess("director.run_playout")
    m.start()
    m.backoff = 60.0  # pretend it had already failed a few times before
    m.started_at -= HEALTHY_UPTIME_SECONDS + 1  # simulate it having run long enough

    m.poll_and_maybe_restart()

    assert m.backoff == MIN_BACKOFF_SECONDS


def test_poll_and_maybe_restart_restarts_a_crashed_process_and_escalates_backoff(tmp_path, monkeypatch):
    proc1 = FakeProc(pid=1)
    proc2 = FakeProc(pid=2)
    make_process(tmp_path, monkeypatch, [proc1, proc2])

    m = ManagedProcess("director.run_ticker")
    m.start()
    proc1.returncode = 1  # crashed

    m.poll_and_maybe_restart()

    assert m.proc is proc2  # replaced with a fresh process
    assert m.backoff == MIN_BACKOFF_SECONDS * 2  # escalated after the failure


def test_stop_terminates_a_running_process_but_not_an_already_exited_one(tmp_path, monkeypatch):
    proc = FakeProc()
    make_process(tmp_path, monkeypatch, [proc])

    m = ManagedProcess("director.run_playout")
    m.start()
    m.stop()

    assert proc.terminated is True

"""Running a command in the attached folder.

This is the slice where the folder stops being the only thing that matters. ADR-007 is explicit:
path confinement bounds where *files* are touched, not what a *process* may do once it is running.
A command here has the user's own privileges and the user's own toolchain.

So what these tests pin is not "the command cannot escape" — it can, and the ADR says so. They pin
the things that are actually promised: it runs in the root, it stops when it is told to, it stops on
its own eventually, its output is bounded, its failures are data, and Orrery's own secrets do not
ride along in its environment.
"""
import os
import sys

import pytest

from backend.features import workspace_run

pytestmark = pytest.mark.anyio


@pytest.fixture
def root(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return project


def _echo(text: str) -> str:
    return f"echo {text}"


# --- it runs where it says it runs ------------------------------------------------------------

async def test_a_command_runs_with_the_root_as_its_working_directory(root):
    out = await workspace_run.run_command(root, "python -c \"import os;print(os.getcwd())\"")

    assert out["exit_code"] == 0
    assert out["stdout"].strip().lower() == str(root.resolve()).lower()


async def test_the_result_says_which_shell_actually_ran_it(root):
    """"Run a command" is meaningless without knowing what interpreted it — the same line does
    different things in bash, PowerShell and cmd."""
    out = await workspace_run.run_command(root, _echo("hello"))

    assert out["shell"] in {"bash", "powershell", "cmd", "sh"}
    assert out["cwd"] == str(root.resolve())


async def test_a_failing_command_is_data_not_an_exception(root):
    out = await workspace_run.run_command(root, "python -c \"import sys;sys.exit(3)\"")

    assert out["exit_code"] == 3
    assert out["timed_out"] is False


async def test_stderr_is_captured_separately_from_stdout(root):
    out = await workspace_run.run_command(
        root, "python -c \"import sys;print('out');print('err',file=sys.stderr)\""
    )

    assert "out" in out["stdout"]
    assert "err" in out["stderr"]


async def test_an_empty_command_is_refused(root):
    for command in ("", "   ", "\n"):
        with pytest.raises(ValueError):
            await workspace_run.run_command(root, command)


# --- it stops -----------------------------------------------------------------------------------

async def test_a_command_that_never_ends_is_killed_and_says_so(root):
    out = await workspace_run.run_command(
        root, "python -c \"import time;time.sleep(30)\"", timeout=2
    )

    assert out["timed_out"] is True
    assert out["exit_code"] != 0        # a timeout that reported success would be a lie


async def test_a_timeout_kills_the_children_too_not_just_the_shell(root, tmp_path):
    """Killing the shell and leaving its children is how a "stopped" command keeps writing to the
    user's folder minutes later. The grandchild here outlives its parent unless the whole tree goes."""
    marker = tmp_path / "still-running.txt"
    child = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',\"import time;time.sleep(8);open(r'{marker}','w').write('x')\"]);"
        "time.sleep(30)"
    )
    await workspace_run.run_command(root, f'python -c "{child}"', timeout=2)

    import asyncio
    await asyncio.sleep(9)

    assert not marker.exists(), "a grandchild survived the timeout and kept working"


async def test_cancelling_the_turn_kills_the_command(root):
    import asyncio

    task = asyncio.create_task(
        workspace_run.run_command(root, "python -c \"import time;time.sleep(30)\"", timeout=60)
    )
    await asyncio.sleep(1.0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# --- it stays inside its budget ------------------------------------------------------------------

async def test_a_flood_of_output_is_bounded_and_says_it_was_cut(root):
    out = await workspace_run.run_command(
        root, "python -c \"print('x'*200000)\"", timeout=30
    )

    assert len(out["stdout"]) <= workspace_run.MAX_STDOUT_CHARS
    assert out["truncated"] is True


async def test_truncation_keeps_the_end_where_the_error_usually_is(root):
    """A build that fails prints thousands of lines and then the reason. Keeping only the head
    throws away the only part anyone wanted."""
    script = "print('x'*120000);print('THE ACTUAL ERROR')"
    out = await workspace_run.run_command(root, f'python -c "{script}"', timeout=30)

    assert "THE ACTUAL ERROR" in out["stdout"]
    assert out["truncated"] is True


async def test_a_timeout_beyond_the_ceiling_is_refused(root):
    with pytest.raises(ValueError):
        await workspace_run.run_command(root, "echo hi", timeout=workspace_run.MAX_TIMEOUT + 1)


# --- Orrery's own secrets do not ride along -------------------------------------------------------

async def test_the_command_does_not_inherit_orrerys_database_url(root, monkeypatch):
    """The command sees the user's real environment, which is the point. It should not additionally
    be handed Orrery's own credentials just because Orrery is the process that spawned it."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://orrery:hunter2@localhost/orrery")
    monkeypatch.setenv("ORRERY_ADMIN_TOKEN", "super-secret")
    monkeypatch.setenv("PATH", os.environ["PATH"])

    out = await workspace_run.run_command(
        root,
        "python -c \"import os;print(os.environ.get('DATABASE_URL','-'),os.environ.get('ORRERY_ADMIN_TOKEN','-'))\"",
    )

    assert "hunter2" not in out["stdout"]
    assert "super-secret" not in out["stdout"]


async def test_the_command_still_gets_a_normal_environment(root):
    """Scrubbing Orrery's variables must not strip the user's toolchain — a command that cannot see
    PATH is a command that cannot run anything, which is not what "like a normal terminal" means."""
    out = await workspace_run.run_command(
        root, "python -c \"import os;print(bool(os.environ.get('PATH')))\""
    )

    assert out["stdout"].strip() == "True"


# --- the accident guard ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm -rf /",
    "rm -rf / --no-preserve-root",
    "sudo rm -rf /*",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    ":(){ :|:& };:",
])
def test_commands_that_destroy_the_machine_are_refused(command):
    """A deny-list is not a sandbox and this one does not pretend to be: anyone who wants past it
    walks past it. It exists for the other case, which is the likely one — a model that has
    misunderstood the task and reaches for something catastrophic. ADR-007 is honest that a running
    process is not confined; that is a reason to catch the obvious cases, not to catch none."""
    assert workspace_run.refuses(command)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-shaped destruction")
@pytest.mark.parametrize("command", [
    "del /f /s /q C:\\*",
    "format C: /y",
    "Remove-Item -Recurse -Force C:\\",
])
def test_the_windows_shaped_versions_are_refused_too(command):
    assert workspace_run.refuses(command)


@pytest.mark.parametrize("command", [
    "npm install",
    "git push origin main",
    "rm -rf node_modules",       # inside the project, and exactly what people mean
    "pytest -q",
    "python manage.py migrate",
])
def test_ordinary_project_commands_are_not_refused(command):
    """The guard has to stay narrow. A deny-list that catches real work is a deny-list people
    disable, and then it catches nothing at all."""
    assert not workspace_run.refuses(command)


async def test_a_refused_command_never_starts(root):
    with pytest.raises(workspace_run.RefusedCommand):
        await workspace_run.run_command(root, "rm -rf /")


# --- the loop the app actually runs on -------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="the Selector/Proactor split is Windows-only")
def test_a_command_runs_on_the_event_loop_the_app_actually_uses():
    """app.py pins the *Selector* loop on Windows, because psycopg async requires it — and the
    Selector loop does not implement subprocesses at all. `asyncio.create_subprocess_exec` therefore
    raises NotImplementedError in the one configuration Orrery ships in, while passing every test
    run on a Proactor loop. This runs the command on the production loop, which is the only place
    that distinction shows up.
    """
    import asyncio

    loop = asyncio.SelectorEventLoop()
    try:
        out = loop.run_until_complete(_run_in(loop))
    finally:
        loop.close()

    assert out["exit_code"] == 0
    assert "ran" in out["stdout"]


async def _run_in(_loop):
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        return await workspace_run.run_command(folder, "python -c \"print('ran')\"")

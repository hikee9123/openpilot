import errno
import fcntl
import os
import sys
import pathlib
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params

CUSTOM_MODEL_COMPILE_STATUS = "CustomModelCompileStatus"
CUSTOM_MODEL_COMPILE_NAME = "CustomModelCompileName"
CUSTOM_MODEL_COMPILE_FINISHED_AT = "CustomModelCompileFinishedAt"
CUSTOM_MODEL_COMPILE_ERROR = "CustomModelCompileError"
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"

def unblock_stdout() -> None:
  # get a non-blocking stdout
  child_pid, child_pty = os.forkpty()
  if child_pid != 0:  # parent

    # child is in its own process group, manually pass kill signals
    signal.signal(signal.SIGINT, lambda signum, frame: os.kill(child_pid, signal.SIGINT))
    signal.signal(signal.SIGTERM, lambda signum, frame: os.kill(child_pid, signal.SIGTERM))

    fcntl.fcntl(sys.stdout, fcntl.F_SETFL, fcntl.fcntl(sys.stdout, fcntl.F_GETFL) | os.O_NONBLOCK)

    while True:
      try:
        dat = os.read(child_pty, 4096)
      except OSError as e:
        if e.errno == errno.EIO:
          break
        continue

      if not dat:
        break

      try:
        sys.stdout.write(dat.decode('utf8'))
      except (OSError, UnicodeDecodeError):
        pass

    # os.wait() returns a tuple with the pid and a 16 bit value
    # whose low byte is the signal number and whose high byte is the exit status
    exit_status = os.wait()[1] >> 8
    os._exit(exit_status)


def write_onroad_params(started, params):
  params.put_bool("IsOnroad", started)
  params.put_bool("IsOffroad", not started)


def init_custom_model_compile_state(params: Params) -> None:
  status = params.get(CUSTOM_MODEL_COMPILE_STATUS)
  status_text = status.decode("utf-8") if isinstance(status, bytes) else str(status or "")
  if status_text != STATUS_RUNNING:
    return

  model_name = params.get(CUSTOM_MODEL_COMPILE_NAME)
  model_name_text = model_name.decode("utf-8") if isinstance(model_name, bytes) else str(model_name or "")
  params.put(CUSTOM_MODEL_COMPILE_STATUS, STATUS_FAILED)
  params.put(CUSTOM_MODEL_COMPILE_NAME, model_name_text)
  params.put(CUSTOM_MODEL_COMPILE_FINISHED_AT, str(int(time.time())))
  params.put(CUSTOM_MODEL_COMPILE_ERROR, "compile interrupted by device or manager restart")


def logging_enabled(params: Params) -> bool:
  enable_logging = params.get("EnableLogging")
  enabled = True if enable_logging is None else params.get_bool("EnableLogging")
  return enabled and not params.get_bool("DisableLogging")


def save_bootlog():
  params = Params()
  if not logging_enabled(params):
    return

  # copy current params
  tmp = tempfile.mkdtemp()
  params_dirname = pathlib.Path(params.get_param_path()).name
  params_dir = os.path.join(tmp, params_dirname)
  shutil.copytree(params.get_param_path(), params_dir, dirs_exist_ok=True)

  def fn(tmpdir):
    env = os.environ.copy()
    env['PARAMS_COPY_PATH'] = tmpdir
    subprocess.call("./bootlog", cwd=os.path.join(BASEDIR, "system/loggerd"), env=env)
    shutil.rmtree(tmpdir)
  t = threading.Thread(target=fn, args=(tmp, ))
  t.daemon = True
  t.start()

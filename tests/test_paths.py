"""agv_core.paths: one resolution of the state and maps directories (lean plan D24)."""
import os

from helpers import check

from agv_core import paths


def _with_env(env, fn):
    saved = {k: os.environ.get(k) for k in (paths.STATE_ENV, paths.MAPS_ENV)}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_paths():
    print("\npaths: env first, then the expanded default")
    home = os.path.expanduser("~")
    both = lambda: (paths.state_dir(), paths.maps_dir())  # noqa: E731
    got = _with_env({paths.STATE_ENV: None, paths.MAPS_ENV: None}, both)
    check("unset: ~/.amr and ~/amr_maps, expanded",
          got == (os.path.join(home, ".amr"), os.path.join(home, "amr_maps")), str(got))
    got = _with_env({paths.STATE_ENV: "", paths.MAPS_ENV: ""}, both)
    check("an empty variable counts as unset", got[0].startswith(home) and got[0].endswith(".amr"), str(got))
    got = _with_env({paths.STATE_ENV: "/data/amr", paths.MAPS_ENV: "~/m"},
                    lambda: (paths.state_dir(), paths.maps_dir(), paths.logs_dir(), paths.mls_cal_dir()))
    check("set: the variable wins, ~ in it expanded, sub-paths follow",
          got == ("/data/amr", os.path.join(home, "m"), "/data/amr/logs", "/data/amr/mls_cal"), str(got))
    env = paths.env_for("~/s", "/m")
    check("env_for hands a child the same directories",
          env == {paths.STATE_ENV: os.path.join(home, "s"), paths.MAPS_ENV: "/m"}, str(env))


TESTS = [test_paths]

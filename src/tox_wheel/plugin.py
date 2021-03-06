from contextlib import contextmanager
from functools import partial

import pluggy
import py
from tox import package
from tox.package import get_package

hookimpl = pluggy.HookimplMarker("tox")


@hookimpl
def tox_addoption(parser):
    parser.add_argument(
        "--wheel",
        action="store_true",
        help="Use bdist_wheel instead of sdist",
    )
    parser.add_argument(
        "--wheel-dirty",
        action="store_true",
        help="Do not remove build directory (fast but dirty builds)",
    )
    parser.add_testenv_attribute(
        name="wheel",
        type="bool",
        default=False,
        help="Use bdist_wheel instead of sdist",
    )
    parser.add_testenv_attribute(
        name="wheel_dirty",
        type="bool",
        default=False,
        help="Do not remove build directory (fast but dirty builds)"
    )
    parser.add_testenv_attribute(
        name="wheel_build_env",
        type="string",
        default='{envname}',
        help="Environment to use for building the wheel. Default: %(default)r"
    )


@contextmanager
def patch(obj, attr, value):
    original = getattr(obj, attr)
    setattr(obj, attr, value)
    try:
        yield
    finally:
        getattr(obj, attr, original)


@hookimpl
def tox_package(session, venv):
    if hasattr(session, "package"):
        return session.package
    if session.config.option.wheel or venv.envconfig.wheel:
        build_venv = session.getvenv(venv.envconfig.wheel_build_env)
        if not hasattr(build_venv, "wheel_package"):
            with patch(package, 'build_package', partial(wheel_build_package, venv=build_venv)):
                build_venv.wheel_package, build_venv.wheel_dist = get_package(session)
        return build_venv.wheel_package


def wheel_build_package(config, report, session, venv):
    if config.isolated_build:
        report.warning("Disabling isolated_build, not supported with wheels.")
    return wheel_build(report, config, session, venv)


def wheel_build(report, config, session, venv):
    setup = config.setupdir.join("setup.py")
    if not setup.check():
        report.error("No setup.py file found. The expected location is: {}".format(setup))
        raise SystemExit(1)
    with session.newaction(venv, "packaging") as action:
        action.setactivity("wheel-make", setup)
        if not (session.config.option.wheel_dirty or venv.envconfig.wheel_dirty):
            action.setactivity("wheel-make", "cleaning up build directory ...")
            session.make_emptydir(config.setupdir.join("build"))
        session.make_emptydir(config.distdir)

        def wheel_is_allowed_external(path, is_allowed_external=venv.is_allowed_external):
            if not is_allowed_external(path):
                raise RuntimeError("Couldn't find interpreter inside {} for building".format(venv))
            return True

        with patch(venv, 'is_allowed_external', wheel_is_allowed_external):
            venv.update(action=action)
            venv.test(
                name="wheel-make",
                commands=[["python", setup, "bdist_wheel", "--dist-dir", config.distdir]],
                redirect=False,
                ignore_outcome=False,
                ignore_errors=False,
                display_hash_seed=False,
            )
        try:
            return config.distdir.listdir()[0]
        except py.error.ENOENT:
            # check if empty or comment only
            data = []
            with open(str(setup)) as fp:
                for line in fp:
                    if line and line[0] == "#":
                        continue
                    data.append(line)
            if not "".join(data).strip():
                report.error("setup.py is empty")
                raise SystemExit(1)
            report.error(
                "No dist directory found. Please check setup.py, e.g with:\n"
                "     python setup.py sdist"
            )
            raise SystemExit(1)

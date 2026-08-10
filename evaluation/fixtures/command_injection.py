"""A shell out with an interpolated argument, and a list form that is safe."""

import subprocess


def archive(name: str) -> None:
    subprocess.call("tar czf " + name + ".tgz " + name, shell=True)


def archive_safely(name: str) -> None:
    subprocess.run(["tar", "czf", f"{name}.tgz", name], check=True)

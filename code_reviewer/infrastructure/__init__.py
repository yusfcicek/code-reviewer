"""Infrastructure layer: adapters onto GitLab, vLLM, the filesystem and grep.

Everything here implements a port declared in ``application.ports``. Nothing in
the layers above imports from this package except the composition root.
"""

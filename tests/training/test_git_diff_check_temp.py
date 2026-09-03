"""Temporary CI proof that the planner experiment passes git diff --check."""
from __future__ import annotations

import subprocess


BASE = "4d9e3d6b46c23ecabd7cfbde6453761412353d92"


def test_planner_branch_git_diff_check():
    subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", BASE],
        check=True,
        text=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "diff", "--check", f"{BASE}..HEAD"],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

"""Share checked build results across worktrees of the same clone."""
from pathlib import Path
import subprocess


def cache_root(repo):
    repo = Path(repo).resolve()
    if not (repo / '.git').exists():
        return repo / '.cache'
    try:
        common = subprocess.check_output(
            ['git', '-C', str(repo), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
            stderr=subprocess.DEVNULL, text=True).strip()
        return Path(common).resolve().parent / '.cache'
    except (OSError, subprocess.CalledProcessError):
        return repo / '.cache'

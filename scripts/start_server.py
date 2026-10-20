"""Initialize the counter volume, then drop privileges before serving requests."""

import os
from pathlib import Path
import pwd
import sys

if os.getuid() == 0:
    account = pwd.getpwnam("workshop")
    directory = Path(
        os.environ.get("WORKSHOP_USAGE_DB", "/tmp/workshop-usage.sqlite3")
    ).parent
    directory.mkdir(parents=True, exist_ok=True)
    if directory != Path("/tmp"):
        os.chown(directory, account.pw_uid, account.pw_gid)
        os.chmod(directory, 0o700)
    os.initgroups(account.pw_name, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
os.execvp(sys.argv[1], sys.argv[1:])

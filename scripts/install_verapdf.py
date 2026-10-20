"""Build-time install of a checksum-pinned upstream veraPDF distribution."""

from hashlib import sha256
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

URL = (
    "https://software.verapdf.org/releases/1.30/verapdf-greenfield-1.30.3-installer.zip"
)
SHA256 = "b512bf24945503a33fc10738ecffc1f2dccaaf8593a448e94ee9ac86a9559a59"
with tempfile.TemporaryDirectory() as folder:
    archive = Path(folder) / "installer.zip"
    with urllib.request.urlopen(URL, timeout=90) as response:
        data = response.read(40 * 1024 * 1024)
    if sha256(data).hexdigest() != SHA256:
        raise RuntimeError("veraPDF installer checksum mismatch")
    archive.write_bytes(data)
    with zipfile.ZipFile(archive) as z:
        z.extractall(folder)
    subprocess.run(
        [
            "java",
            "-jar",
            str(
                Path(folder)
                / "verapdf-greenfield-1.30.3/verapdf-izpack-installer-1.30.3.jar"
            ),
            "scripts/verapdf-install.xml",
        ],
        check=True,
        timeout=120,
    )

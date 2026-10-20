"""Emit build evidence without reading application configuration or credentials."""

from importlib.metadata import distributions
import json
from pathlib import Path
import subprocess

packages = []
for dist in distributions():
    meta = dist.metadata
    packages.append(
        {
            "name": meta["Name"],
            "version": dist.version,
            "license_expression": meta.get("License-Expression"),
            "license_metadata": meta.get("License"),
            "license_classifiers": [
                value
                for value in meta.get_all("Classifier", [])
                if value.startswith("License ::")
            ],
            "license_files": meta.get_all("License-File", []),
        }
    )
result = {
    "python_distributions": sorted(packages, key=lambda p: p["name"].lower()),
    "vendored": [
        {
            "name": "DAYamlChecker DOCX core",
            "upstream_commit": "d5545ec639a900504cca7434ba8f841330cd2650",
            "patch_commit": "0df3054",
            "license": "MIT",
            "source": "https://github.com/SuffolkLITLab/DAYamlChecker/pull/97",
        }
    ],
    "notice": "License metadata is reported as supplied by each package. Missing metadata is not a license determination. Installed license texts remain in their distributions.",
}
try:
    result["system_packages"] = subprocess.run(
        ["dpkg-query", "-W", "-f=${Package}\t${Version}\n"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    result["system_licenses"] = (
        "/usr/share/doc/<package>/copyright in the deployed image"
    )
except (OSError, subprocess.CalledProcessError):
    pass
try:
    result["verapdf"] = subprocess.run(
        ["/opt/verapdf/verapdf", "--version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    ).stdout.strip()
except (OSError, subprocess.SubprocessError):
    result["verapdf"] = "not installed"
print(json.dumps(result, indent=2))

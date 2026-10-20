Source: https://github.com/SuffolkLITLab/DAYamlChecker

Pinned upstream commit: d5545ec639a900504cca7434ba8f841330cd2650.

Only the framework-independent DOCX checker and diagnostic registry are vendored.
Local patches add logical filenames, strict parse reporting, effective language,
on/off table headers and object paths. The relative messages import is the only
packaging change. See LICENSE for the retained MIT notice.

Upstream fixes: https://github.com/SuffolkLITLab/DAYamlChecker/pull/97
Patch commit: 0df3054. The vendored implementation includes those changes.

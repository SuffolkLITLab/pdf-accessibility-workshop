# Third-party sources and runtime components

The PDF core and original workshop UI were extracted from Suffolk LIT Lab's
MIT-licensed ALDashboard. This repository retains its MIT notice in LICENSE.

The DOCX checker and diagnostics are pinned copies of DAYamlChecker at
`d5545ec639a900504cca7434ba8f841330cd2650`, with the fixes proposed in
https://github.com/SuffolkLITLab/DAYamlChecker/pull/97. The original MIT copyright
and permission notice is retained at `workshop/vendor/dayamlchecker/LICENSE`.
This lightweight vendored bridge avoids importing the checker's YAML/spelling
initializer. It is not a forked second rule implementation; changes should be
upstreamed and the pinned copy updated together. A separately installable shared
core remains a later packaging milestone.

veraPDF 1.30.3 is installed from its checksum-pinned official binary distribution.
It offers GPLv3+ or MPLv2+ licensing; this distribution uses the MPLv2+ option.
Its source and notices are available at https://github.com/veraPDF and
https://github.com/veraPDF/veraPDF-apps/tree/v1.30.3. The upstream executable
retains its copyright/license header. No veraPDF source modifications are made.

Build-time `runtime-dependencies.json` records the actual Python and Debian
package versions and Python license metadata in the image. Debian copyright
texts remain under `/usr/share/doc/<package>/copyright`. Python license files
remain with installed distributions. Missing metadata is reported, not guessed.
Native review ZIP exports include this inventory when built in the deployment
image. PDF.js is loaded from cdnjs at 4.0.379 (Apache-2.0), as in the extracted host.

LIT Lab logos come from https://github.com/SuffolkLITLab/logos. Bundled Albert
Sans carries its SIL Open Font License in `web/static/brand/AlbertSans-OFL.txt`. Existing
workshop fonts are served through Google Fonts. The generated DOCX/PPTX test
fixtures contain only text and geometry authored for this repository; no client
documents are included.

DOCX paragraph style/property edits use python-docx 1.2.0 (MIT), copyright
Steve Canny. Its installed license is included in the runtime dependency inventory.

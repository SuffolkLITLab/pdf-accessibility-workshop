# Native Office workshop: release scope and evidence

The existing Flask extraction remains the application. Its PDF engine, native
workshop UI, compatibility endpoints, authentication model (public, no sign-in),
Fly app, and browser IndexedDB project storage remain in place. No Docassemble
runtime is imported by ordinary inspection/repair operations. Office operations
use framework-independent `workshop/office`, contracts, and services.

## Implemented

- Actual-format recognition, bounded OPC ZIP/XML reading, no external relationship
  fetching, required-part errors, named incomplete optional-part coverage.
- Immutable content-addressed versions, SHA-256-bound plans, version-scoped native
  targets with fingerprints, deterministic retry results, preservation receipts,
  reinspection, browser history/undo and reload persistence.
- All 28 DOCX rule families and publication-markup review from the pinned checker.
  Natural codes/severities remain available. Fixes cover malformed XML, unused
  language styles, false header toggles, duplicate table targets and logical names.
- DOCX title, default/selected text language, supported DrawingML descriptions and
  decorative choices, accessible table names, confirmed simple table headers, and
  Title/Body text/Heading 1–9 paragraph roles. Text selection applies to containing
  paragraphs; body-text replacement is not offered.
- PPTX slide-list order, native/inherited title placeholders (including off-slide
  titles), shape/group inventories, descriptions/decorative choices, applicable
  language/font defaults, table/link/media inventories, and explicit complex-content
  coverage. Edits support metadata, existing simple title placeholders, descriptions,
  decorative choices, language, and simple-table first-row formatting.
- Three-stage Office UI, semantic views, contextual objects, explicit human notes,
  external-test records, native file export, readable report, portable JSON manifest.
  Existing PDF review snapshots use tagged JSON for Sets, Maps and dates in manifests.
- Explicit queued PDF/UA-1 validation in the PDF host; API also accepts ua2. The
  selected artifact digest, raw report, profile and engine version accompany results.
  Missing tools, failed processing, timeout, unknown schemas and mismatched profiles
  cannot become passing evidence. Edits invalidate current-version evidence.
- Signed/protected Office packages and signed/encrypted PDFs are inspection-only.
  Authors must create an authorized derivative in the native application to edit.

Content IDs identify bytes. Parent relationships are also retained in operation
receipts and undo history; reinspection of the same bytes produces the same ID.
Neither a no-finding detector result nor a human note is a conformance certificate.

## Deliberate limits and remaining milestones

This is the first native inspection/controlled-repair release, not completion of
all eight milestones. No Office raster renderer, conversion pipeline, Office AI,
complex field-link editor, slide reordering, SmartArt reconstruction, caption
editing, paragraph splitting/list restructuring, or full effective-contrast resolver is enabled.
Unresolved contrast, layout/master semantics, complex tables and media remain
visible review/unsupported coverage. PowerPoint first-row formatting is explicitly
not proof of assistive-technology header semantics. A semantic view is not a
native-application behavior test.

Real Word/PowerPoint and screen-reader pilot tests have not been performed here.
They remain a release-validation gate before expanding automatic edits. Native
files reopen using python-docx/python-pptx and unchanged ZIP member payloads are
verified, but these checks do not establish actual assistive-technology behavior.

The browser stores projects privately to that browser profile, not an authenticated
account. Stateless Office requests clean up temporary files. Validation uses one
bounded in-process executor because this app has one Gunicorn worker and no queue
service. Jobs/results expire after 30 minutes and are lost on restarts. Failed jobs
leave the browser's last usable file intact. Multiple workers or machines require a
shared artifact/job store before enabling that deployment topology. A separate core
package and durable shared worker queue remain later migrations.

## Verification

Portable fixtures cover identical table labels, malformed required/optional XML,
unused/applied language styles, multilingual overrides, false headers, native slide
order, hidden titles, descriptions/decorative choices, table names, paragraph roles, link preservation, template
tokens, unchanged payloads, idempotence, stale plans, exact export hashes and signed
PDF rewrite prevention. Browser tests cover both Office formats through repair,
notes, reload, report download and undo. Existing PDF regressions remain mandatory.

A real local veraPDF 1.30.3 spike on 2026-10-20 produced:

| Input/profile | Result |
| --- | --- |
| Original untagged plain-document.pdf / ua1 | fail |
| Synthetic empty, titled, tagged PDF with UA-1 metadata / ua1 | pass (machine checks only) |
| Malformed PDF / ua1 | processing error |
| Unsupported automatic profile request | unsupported |

The spike identified the current JSON `compliant` key (older reports may use
`isCompliant`). Both are accepted only with a matching explicit profile. Unit tests
also cover PDF/A fallback rejection and timeouts. Set `VERAPDF_TEST_EXECUTABLE` to
run real-tool failure/processing checks alongside pytest.

References: [WCAG2ICT](https://www.w3.org/TR/wcag2ict-22/),
[veraPDF validation](https://docs.verapdf.org/cli/validation/),
[veraPDF installation](https://docs.verapdf.org/install/),
[python-pptx text](https://python-pptx.readthedocs.io/en/latest/user/text.html),
[python-pptx tables](https://python-pptx.readthedocs.io/en/latest/api/table.html).

# Document accessibility workshop

[Open the workshop](https://workshop.suffolklitlab.org/)

A standalone Flask app for reviewing and repairing PDF, DOCX, and PPTX accessibility. Works with
ordinary documents and interactive forms. Form-control checks are not applicable
when a document has no fields.

The PDF workshop finds problems, guides eight reader-facing review tasks, and offers
reading-order playback and export. Machine checks, human decisions, and external
testing remain separate. AI suggestions run only when requested and require human
confirmation. Exporting never automatically declares PDF/UA conformance.

Originally extracted from [ALDashboard](https://github.com/SuffolkLITLab/docassemble-ALDashboard).
This repository owns its PDF engine, browser interface, and Flask adapters. It has
no Docassemble, Redis, or database-server dependency. A bounded in-process worker
runs veraPDF validation; the Docker image includes veraPDF 1.30.3 and Java.

Office review uses the same find/review/export stages with native semantic views,
explicit repairs, immutable history, and file/report/manifest downloads. See
[release scope and remaining work](OFFICE_RELEASE.md) and
[source/dependency notices](THIRD_PARTY_NOTICES.md).

## DOCX semantic repairs

In **Review and repair**, click a block in the simulated document view to open its
settings beside the preview. Ctrl/Cmd-click or Shift-click adds blocks to the selection;
the settings panel also offers keyboard-accessible checkboxes. **Merge adjacent blocks**
combines ordinary adjacent text paragraphs into one paragraph, retaining the first
paragraph's settings and placing a line break between their text. Lists, section
boundaries, tracked edits, fields, drawings and referenced ranges remain separate.
Merge supports undo and deterministic retries against the original digest.

**Heading levels**, **Image alt text**, and **Table names** provide additional batch
and inventory controls below the workspace.

- Highlight text in the read-only paragraph view or select paragraphs with checkboxes,
  then apply Title, Heading 1–9, or Body text. The entire containing paragraphs change
  role; their text, runs, fields, and inline formatting remain intact. Word's existing
  styles are reused, so paragraph appearance can change. Up to 30 paragraphs per repair.
- Edit an image's description or explicitly mark it decorative. Choices target the
  selected drawing instance, including when several drawings reuse one image file.
- Set a table's accessible title in Word table properties (`w:tblCaption`). This does
  not insert a visible caption or alter cells, even for a complex table.

These operations preserve unrelated package member payloads, recheck the document,
record a receipt, and support undo and browser reload. They do not provide general
body-text editing. Native Word/screen-reader behavior still needs reader testing.

Paragraph style/property handling uses [python-docx](https://python-docx.readthedocs.io/en/latest/user/styles-using.html)
without resaving the entire package. Table names use the
[Office table-caption property](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tableproperties.tablecaption?view=openxml-3.0.1).

## Gotenberg layout preview

**Generate PDF layout preview** sends a preview-only copy to the configured Gotenberg
LibreOffice service. Set `GOTENBERG_URL`, `GOTENBERG_USERNAME`, and `GOTENBERG_PASSWORD`
as server secrets (the deployment uses the same service as LITEfile). Basic-auth values
and original filenames are never sent to the browser. Requests disable redirects,
bound the output to 30 MB/100 pages, use a 90-second timeout, and allow at most two
concurrent conversions per process. Externally linked resources and external-content
fields are not converted. No external preview runs during ordinary inspection.

Temporary DOCX bookmarks link PDF named destinations to exact native object IDs;
there is no text-matching locator. Click the PDF's paragraph/image/table markers to
open settings. Unmapped blocks remain editable in the native view. The current
implementation anchors main-document blocks; headers, footers and unsupported layout
structures can be selected through the object selector. Fonts and pagination may differ
from Word. The PDF is a layout aid, not an accessible export or PDF/UA validation.
Edits and undo discard the old preview; a regenerated preview records its source hash.

The original DOCX never receives the temporary bookmarks. Preview bytes are saved
only with that browser's review. `GOTENBERG_*` credentials must not be committed.
See [Gotenberg's conversion options](https://gotenberg.dev/docs/convert-with-libreoffice/convert-to-pdf).

## Saved reviews

Each review has a `/review/<uuid>` URL. The native file, edits, review decisions, external
testing notes, and undo history are saved in **IndexedDB in the current browser**.
Reloading restores the last completed save without rerunning automatic repairs.
The upload screen lists saved reviews and lets you delete them.

Browser storage is also specific to the website address. Reviews saved at
`pdf-accessibility-workshop.fly.dev` remain available there; they do not
automatically move to `workshop.suffolklitlab.org`. The old address stays online.

The URL is not a share link: another browser/device cannot retrieve the document.
Clearing site data removes saved reviews. Private browsing and storage quotas may
prevent saving; the app displays a warning and asks you to export instead. A reload
during a repair restores the last completed operation. Browser storage is not an
archival backup—export finished documents. All users of the same browser profile can
access its saved reviews.

PDF operations upload a temporary working copy to the server, deleted after the
request. AI requests send relevant document content to OpenAI only on explicit
request. The public deployment has no sign-in.

## Run locally

Use Python 3.12+ and install Poppler, Tesseract, Fontconfig and fonts (on Debian:
`poppler-utils tesseract-ocr tesseract-ocr-eng fontconfig fonts-liberation2 fonts-dejavu-core fonts-noto-core`).

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/gunicorn --bind 127.0.0.1:8080 --timeout 240 web.app:app
```

Optional environment variables: `OPENAI_API_KEY`, `OPENAI_MODEL` (default
`gpt-5-mini`), and `OPENAI_ORG_ID` only if needed for the key's organization.
Never commit credentials. Uploads are limited to 30 MB in the browser and 32 MB
per HTTP request.

## Deploy

```sh
flyctl deploy --config fly.toml --remote-only --ha=false
```

The existing Fly app is `pdf-accessibility-workshop`, in the `suffolk-lit-lab`
organization, Newark region. Credentials are Fly secrets and are not in the image.
Import updates through standard input with `flyctl secrets import --app
pdf-accessibility-workshop`. The app runs as an unprivileged user on one 2 GB
machine with HTTPS, automatic stop/start, and a `/healthz` check.

## Custom domain

`workshop.suffolklitlab.org` is attached to the Fly app with an automatically
renewed Let's Encrypt certificate. Cloudflare has a DNS-only CNAME:

```
workshop.suffolklitlab.org → pe30dd3.pdf-accessibility-workshop.fly.dev
```

TTL is 300 seconds. Fly supplies HTTPS directly. Check certificate status with
`flyctl certs check workshop.suffolklitlab.org --app pdf-accessibility-workshop`.
Cloudflare's official `cf` CLI is installed locally; credentials stay in the
user's Cloudflare configuration, outside this repository.

## Tests

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
npm ci
npx playwright install chromium
npm run check
npm test
```

The reload test starts Flask on port 8187; Office browser tests use 8188. It uploads a PDF with no fields,
confirms metadata, reloads a saved URL, checks draft and history preservation,
exports, and deletes the saved review. Set `WORKSHOP_TEST_URL` to run that test
against a deployed instance using an isolated browser context.

## Branding

The landing page follows [suffolklitlab.org](https://suffolklitlab.org/) and
[Suffolk's brand guidelines](https://www.suffolk.edu/about/directory/office-of-marketing-communications/online-resources/brand-guidelines).
Unaltered logos come from [SuffolkLITLab/logos](https://github.com/SuffolkLITLab/logos).
Albert Sans is bundled with its SIL Open Font License. Landing styles are scoped
to `.lit-site`; the workshop retains the original LIT Lab Bootstrap theme,
Schibsted Grotesk, IBM Plex Mono, and workshop styles.

## AI drafts and usage allowances

For DOCX, **Draft repairs with AI** sends a bounded native inventory and up to
four image previews to OpenAI on an explicit click. Suggestions cover metadata,
heading roles, language, table names and image alternatives. Each is validated
against the native repair API, bound to the current document digest, and unchecked
until approved. Applying selected suggestions creates an undoable version; drafts
and selections survive browser reloads. Text rewriting is outside this feature.

The deployed app limits document API requests to 60 per client per minute. Actual
AI provider attempts share allowances of 6 per client per hour, 12 per client per
day, and 40 across the application per UTC day. Failed attempts count; provider
retries are disabled. Each request allows at most 100 KB of text, four inline
images totaling 4 MB, and 8,192 completion tokens (DOCX drafts use 6,000).
These are usage bounds, not an exact dollar budget.

Configure `API_REQUESTS_PER_MINUTE`, `AI_CALLS_PER_CLIENT_HOUR`,
`AI_CALLS_PER_CLIENT_DAY`, and `AI_CALLS_PER_DAY`. `WORKSHOP_LIMITS_ENABLED=1`
enables counters locally; Fly enables them by default. `WORKSHOP_USAGE_DB` points
to SQLite on the `workshop_usage` volume. Counters contain HMAC client identifiers,
not raw IP addresses or document contents, and expire after their window plus a
day. IPv6 clients share a /64 allowance; users behind one network may share limits.
If tracking fails, AI pauses while manual editing remains available. The server
initializes volume permissions and drops privileges before starting Gunicorn.
This deployment uses one machine; additional machines need a shared counter store.

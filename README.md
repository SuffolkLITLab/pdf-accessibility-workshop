# PDF accessibility workshop

[Open the workshop](https://pdf-accessibility-workshop.fly.dev/)

A standalone Flask app for reviewing and repairing PDF accessibility. Works with
ordinary documents and interactive forms. Form-control checks are not applicable
when a document has no fields.

The workshop finds problems, guides eight reader-facing review tasks, and offers
reading-order playback and export. Machine checks, human decisions, and external
testing remain separate. AI suggestions run only when requested and require human
confirmation. Exporting never automatically declares PDF/UA conformance.

Originally extracted from [ALDashboard](https://github.com/SuffolkLITLab/docassemble-ALDashboard).
This repository owns its PDF engine, browser interface, and Flask adapters. It has
no Docassemble, Redis, database-server, or worker dependency.

## Saved reviews

Each review has a `/review/<uuid>` URL. The PDF, edits, review decisions, external
testing notes, and undo history are saved in **IndexedDB in the current browser**.
Reloading restores the last completed save without rerunning automatic repairs.
The upload screen lists saved reviews and lets you delete them.

The URL is not a share link: another browser/device cannot retrieve the document.
Clearing site data removes saved reviews. Private browsing and storage quotas may
prevent saving; the app displays a warning and asks you to export instead. A reload
during a repair restores the last completed operation. Browser storage is not an
archival backup—export finished PDFs. All users of the same browser profile can
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

## Tests

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
npm ci
npx playwright install chromium
npm run check
npm test
```

The reload test starts Flask on port 8187. It uploads a PDF with no fields,
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

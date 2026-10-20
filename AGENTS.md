# PDF accessibility workshop

Keep the app standalone: no Docassemble imports or runtime services. PDF helpers
live in `workshop/`, Flask adapters in `web/`, and browser modules in `web/static/`.

- Machine checks, human review, and external testing are separate evidence.
- Tasks with nothing to review are not applicable, never reviewed or failed.
- Ordinary PDFs do not require form controls.
- Drafts require human confirmation. AI calls require explicit clicks.
- Never declare PDF/UA automatically; only the explicit export control may do so.
- Preserve imported tag trees unless the reviewer chooses replacement. Native tag
  edits and merges must preserve content references and must not rebuild the tree.
- Internal field names are opaque. Accessible-name changes update `/TU` only.
- Rebuild draft trees from all decisions and reapply tag-dependent corrections.
- Review persistence uses IndexedDB with structured clones, preserving Sets, bytes,
  history and evidence. Never serialize PDF.js objects or save in-flight repairs.
- Saved URLs must not expose documents to another browser. Storage errors must be
  visible and must not prevent PDF export or delete the last valid checkpoint.
- Scope landing-page CSS to `.lit-site`; retain the workshop's style dependencies.

Run `python -m pytest tests -q`, `npm run check`, and `npm test`. Verify browser
reload recovery after changes to persistence, and use a PDF without fields when
changing applicability logic. Do not print or commit credentials.

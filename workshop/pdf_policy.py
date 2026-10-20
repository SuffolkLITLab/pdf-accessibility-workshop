"""Rewrite policy independent of the legacy PDF remediation engine."""

import pikepdf


def pdf_edit_policy(path):
    try:
        with pikepdf.open(path) as pdf:
            signed = bool(pdf.Root.get("/Perms", {}).get("/DocMDP"))
            for obj in pdf.objects:
                if isinstance(obj, pikepdf.Dictionary) and (
                    obj.get("/Type") == pikepdf.Name("/Sig")
                    or obj.get("/ByteRange") is not None
                ):
                    signed = True
                    break
            protected = pdf.is_encrypted
            return {
                "editable": not (signed or protected),
                "signed": signed,
                "protected": protected,
                "explanation": (
                    "Signed or encrypted PDFs are inspection-only. Keep the original and create an unsigned, unprotected derivative in your PDF application before making accessibility repairs."
                    if signed or protected
                    else "Repairs create a working copy."
                ),
            }
    except pikepdf.PasswordError:
        return {
            "editable": False,
            "signed": False,
            "protected": True,
            "explanation": "This encrypted PDF requires a password. Keep the original and create an authorized unprotected copy in your PDF application before uploading it.",
        }

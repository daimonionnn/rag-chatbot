#!/usr/bin/env python3
"""
Fix non-latin-1 filenames breaking file ingestion in llama-stack 0.6.0.

Bug: the localfs files provider interpolates the raw filename into a response
header:

    headers={"Content-Disposition": f'attachment; filename="{file_obj.filename}"'}

HTTP header values are latin-1 (Starlette enforces this), so any filename with a
character above U+00FF raises UnicodeEncodeError. llama-stack catches it while
attaching the file to a vector store and reports `status: failed` with an EMPTY
`last_error`, so it looks like a mysterious parsing problem.

This matters for Slovak: á é í ó ú ý ô ä happen to be inside latin-1, but
č ď ľ ĺ ň ŕ š ť ž are NOT — so most Slovak filenames silently fail to ingest.

Fix: emit an RFC 5987 / RFC 6266 encoded header (`filename*=utf-8''<pct-encoded>`)
exactly as Starlette's own FileResponse does, keeping the real filename intact.

Idempotent; exits non-zero if the expected source is not found, so a llama-stack
upgrade cannot silently drop the patch.
"""
from __future__ import annotations

import pathlib
import sys
from importlib.util import find_spec

OLD_HEADER = (
    '            headers={"Content-Disposition": '
    "f'attachment; filename=\"{file_obj.filename}\"'},"
)
NEW_HEADER = (
    '            headers={"Content-Disposition": '
    '"attachment; filename*=utf-8\'\'" + _rfc5987_quote(file_obj.filename)},'
)
HELPER = '''

def _rfc5987_quote(filename: str) -> str:
    """Percent-encode a filename for a Content-Disposition header (RFC 5987).

    Added by patch-content-disposition.py: HTTP headers are latin-1, so raw
    non-latin-1 filenames (e.g. Slovak č/š/ž) would raise UnicodeEncodeError.
    """
    from urllib.parse import quote as _quote

    return _quote(filename, safe="")
'''


def main() -> int:
    spec = find_spec("llama_stack")
    if spec is None or spec.origin is None:
        print("patch: llama_stack not importable", file=sys.stderr)
        return 1
    target = (
        pathlib.Path(spec.origin).parent
        / "providers/inline/files/localfs/files.py"
    )
    if not target.is_file():
        print(f"patch: {target} not found", file=sys.stderr)
        return 1

    src = target.read_text()

    if "_rfc5987_quote" in src:
        print(f"patch: already applied to {target}")
        return 0

    if OLD_HEADER not in src:
        print(
            "patch: expected Content-Disposition line not found — "
            "llama-stack changed, re-check the fix",
            file=sys.stderr,
        )
        return 1

    src = src.replace(OLD_HEADER, NEW_HEADER, 1)

    # Append the helper at module level (after the last import-ish preamble is
    # unnecessary: a module-level def at the end is imported before any call).
    src = src.rstrip("\n") + "\n" + HELPER
    target.write_text(src)
    print(f"patch: applied RFC 5987 Content-Disposition fix to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

Vendored files for the Library reader. The app has no build step, so these are committed as they are and upgraded by hand
from the upstream repositories.

| files | what | license |
|-------|------|---------|
| `view.js`, `epub.js`, `epubcfi.js`, `paginator.js`, `fixed-layout.js`, `overlayer.js`, `progress.js`, `footnotes.js`, `text-walker.js`, `search.js`, `tts.js`, `uri-template.js`, `fb2.js`, `mobi.js`, `comic-book.js`, `pdf.js` | foliate-js by John Factotum, github.com/johnfactotum/foliate-js | MIT, see `LICENSE` |
| `vendor/zip.js` | zip.js by Gildas Lormeau, shipped with foliate-js | BSD 3-Clause |
| `vendor/fflate.js` | fflate by Arjun Barrett, shipped with foliate-js | MIT |
| `vendor/pdfjs/pdf.mjs`, `vendor/pdfjs/pdf.worker.mjs`, `vendor/pdfjs/*.css` | PDF.js by Mozilla, shipped with foliate-js | Apache 2.0 (header of each file) |
| `vendor/pdfjs/standard_fonts/` | Foxit and Liberation fonts for PDFs that do not embed theirs | see `LICENSE_FOXIT` (BSD-style) and `LICENSE_LIBERATION` (SIL OFL 1.1) |

Left out on purpose: foliate's own reader page and UI, its PDF source maps, and PDF.js's CJK character maps (`cmaps/`), so some
Chinese, Japanese or Korean PDFs may show gaps.

Two local changes, both marked with a comment starting "Curodav:" in `pdf.js`: a PDF opens one page at a time unless the reader
asks for spreads, and the page's text layer announces itself (`cc-render`) once drawn so highlights and search marks can be put on it.

Security. The reader page (`/library/<entry>/read`) has its own content security policy (`security_headers.py`): book frames may
be `blob:` documents with inline styles, images and fonts, and pdf.js may start a worker. Scripts stay limited to the app's own
files and the page's nonce, and the book frames inherit that, so scripts inside a book never run. foliate needs `allow-scripts` on
its sandboxed frames because of a WebKit bug; the policy is what keeps book scripts out. Links that leave a book open in a new tab
only for http, https and mail addresses.

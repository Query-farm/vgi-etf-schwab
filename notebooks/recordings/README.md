# Official Schwab holdings page recordings

Eight pages were captured on 2026-11-14 through the worker's normal `curl_cffi` transport, without accounts or credentials: two pages for SCHD (102 advertised and parsed rows), six for SCHV (568 rows). `manifest.json` contains exact URLs, UTC capture times, page counts, stored SHA-256 and original HTTP-body SHA-256.

Files contain the complete decoded response text, saved as UTF-8; they have not been filtered to holdings tables or edited. Original and saved hashes distinguish text decoding from byte identity. The release's own HTML parser still extracts the holdings and pagination metadata during notebook execution. Unknown recorded URLs fail; checksums must match. These are real pages, not synthetic portfolios.

The endpoint publishes current holdings only. The page's effective date is shown dynamically by the notebook and differs from capture time. Separate page responses are not an atomic snapshot. The notebook requires complete advertised pagination, a consistent source date per fund and no failed requests before comparing weights. That verifies page coverage against the issuer's count, not the underlying completeness or accuracy of the issuer data.

Source: [Schwab Asset Management](https://www.schwabassetmanagement.com/). The captured data and page content remain separate from the repository's code license; consult the provider's terms for reuse. No affiliation or endorsement is implied.

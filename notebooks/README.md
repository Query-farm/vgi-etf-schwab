# Executed Schwab holdings overlap walkthrough

[How much reported weight is shared?](01_audit_shared_holdings.ipynb) matches SCHD and SCHV by nonempty CUSIP, groups repeated positive-weight rows, verifies a common-weight identity, and explores how a minimum shared-weight threshold changes the selected count and weight. SQL performs the analysis; the real released worker parses the holdings. This is a descriptive data comparison, not an investment recommendation or return-correlation estimate.

## Run without the worker checkout

Install [uv](https://docs.astral.sh/uv/) and Python 3.13 or 3.14. First use needs network access for the remote package, dependencies and VGI extension. Copy the complete `notebooks/` directory anywhere; no root source or `.venv` discovery is used.

```sh
cd notebooks
uv sync --frozen
uv run --frozen python execute.py --timeout 180
```

The notebook has a separate locked environment with Haybarn `2.0.0rc11`. The runner uses that interpreter with a temporary kernel and notebook-directory cwd. Successful outputs are saved atomically; failure leaves the last successful example unchanged. For an interactive editor, register and select this kernel:

```sh
uv run --frozen python -m ipykernel install --user --name vgi-schwab-notebooks --display-name 'Python (Schwab notebooks)'
```

The notebook expects this directory as cwd. Parameters, connection and analytical SQL are visible; helper, plotting and cleanup source are folded. Official local image assets are unchanged.

## Focused experiment and live mode

`MIN_SHARED_PP=0.10` requires a CUSIP to have at least 0.10 percentage points of reported assets in **each** fund. It accepts finite numbers 0–5 inclusive, with zero including every positive-weight shared identifier. Raise only this threshold to 0.50:

```sh
uv run --frozen python execute.py --timeout 180 --parameters '{"MIN_SHARED_PP":0.50}' --output-dir artifacts/half-point
```

Reset to 0.10 for the default. Overrides require a separate destination; successful copies include branding, recordings, support, adapter, runner, environment lock and README. Logs, request audits, extracted charts and experiment copies are ignored by Git.

`DATA_MODE="recorded"` uses eight official pages captured November 14, 2026. The released parser handles the original decoded HTML text, and its own pagination metadata drive the completeness audit. `DATA_MODE="live"` uses the release's normal official client for the same two funds:

```sh
uv run --frozen python execute.py --timeout 180 --parameters '{"DATA_MODE":"live"}' --output-dir artifacts/live
```

There is no historical date parameter. Effective dates and run/capture clocks are distinct; independent pages are not an atomic snapshot. Live endpoint failures are exposed without replay fallback. The existing worker propagates first-page failures but can return a partial list after later-page failure. The adapter audits every request, including failures, and SQL rejects incomplete advertised totals, duplicate or noncontiguous pages, and mixed/missing dates before computing overlap. It does not retry blocked requests through another transport.

## Tested literal release launch

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'schwab' (TYPE vgi, LOCATION 'uvx --python 3.13 --with vgi-python==0.51.0 --with vgi-rpc==0.53.1 --with pyarrow==26.0.1 --with numpy==2.5.4 --with curl-cffi==0.17.0 --from git+https://github.com/Query-farm/vgi-etf-schwab@v0.4.0 python recorded_worker.py');
```

The remote release `v0.4.0` resolves to `36a89f7dd2db2e30c3fe23007b6134731272cf6e`. `uvx` installs the released package and runs the local transport adapter with its interpreter. Existing worker factories, catalog, parsing and pushdown remain unchanged. The adapter returns exact verified recorded response text or calls `make_schwab_get()` in live mode. It allows only SCHD/SCHV holdings URLs, records page metadata with the release's `parse_holdings_page`, and computes no weights or matches. The notebook stages audit metadata in an ordinary local SQL table. The live client is the package's existing `curl_cffi` implementation; no credentials are required.

The original console entry point was independently verified through published Haybarn as well. To upgrade the release or runtime pins, revalidate the default, experiment, live path, page audit and identifier semantics. No SQL engine is built, and root source dependencies/locks stay unchanged.

## Provenance, units and limits

See [recording notes](recordings/README.md) and [manifest](recordings/manifest.json) for exact URLs, UTC capture timestamps, sizes and hashes. Captured pages are real official content, not synthetic data, and remain separate from the code license.

Reported weights use percentage points: 4.49 means 4.49% of that fund's reported assets. Displayed market values are abbreviated by the site and are not used to recompute weights. We do not normalize each list to 100. Blank identifiers, unknown weights, zero and negative positions are visible in diagnostics. Unknown identified weights stop the comparison. Positive rows are grouped by fund and CUSIP only after date and page validation.

For each identifier in the union of identified positive subsets, `a` and `b` are each fund's summed reported positive weight, zero only for absence from that defined complete subset. Common weight is `min(a,b)`. Its sum agrees with `(sum(a)+sum(b)-sum(abs(a-b)))/2`. This is an unnormalized known-positive-weight comparison; missing identifiers and nonpositive exposures are excluded. CUSIP identity does not consolidate all issuers or establish equal economic exposures. The threshold is an analytical choice, not an industry standard.

The first chart uses logarithmic axes explicitly labeled in percentage points. The second separates identifier count and common-weight units into panels. All calculations and result prose derive from SQL; saved plots never refetch holdings.

## Validation

Verified on macOS arm64 through published Haybarn:

- Default and 0.50-point experiment ran from a copied notebooks-only directory in 3.8 s and 3.5 s; complete live mode passed in 6.5 s. Each has 17 code cells, eight SQL cells, two charts, ten overlap invariants and explicit pagination validation. All six charts were inspected.
- Eight pages reconcile to 102 SCHD and 568 SCHV rows, both dated 2026-11-12. Full overlap is 55 shared positive-weight CUSIPs and 17.41 percentage points of common weight. Raising the cutoff 0.10→0.50 selects 33→13 identifiers and 16.34→11.56 points, while full overlap and input rows remain fixed. Live validation returned the same dates and values at that run time.
- Three runner guards preserve successful defaults. A separate fault-injection copy removed the final SCHV page from its replay manifest: the release returned a truncated list, and the notebook correctly rejected it at the pagination check without overwriting that copy's successful notebook.
- All three saved runs pass structural review; Ruff lint and format pass. Image assets and stored recording hashes are verified unchanged.
- Current source gates, separate from release execution: 16 pytest tests, 18 live/schema SQL assertions in two cases, Ruff lint/format, strict mypy (seven source files), and metadata score 100 L1 with zero findings at fail-on-info. Metadata used the repository's requested `--no-execute`; live behavior is covered by the SQL suite and full notebook, not misreported as L2 metadata validation. External-link and paid AI passes were not run.

Root source and `uv.lock` are unchanged. Raw validation logs, extracted charts, audit files and experiment/live copies are under ignored `artifacts/`.

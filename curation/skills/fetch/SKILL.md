---
name: fetch
disable-model-invocation: true
description: "The next batch of a run: its selected publications' full texts downloaded into the run's pool, and up to 20 whose download is complete formed into a batch for the curate skill. Use when the user asks to fetch or download publications or to prepare a batch; the prompt may set the run."
---

# Fetch a batch

You form the next batch of a run: up to 20 of its publications whose download is complete, the article and every supplementary file it lists. A publication whose download is not complete stays in the run's pool and never reaches a curator. You download and convert; you never read a full text and never write to the database. Read no doc: this skill is the whole process.

You download the publications one after another: each is taken as far as it can go, the tools then the browser, and its line written in the pool's status, before the next one starts. The browser is the last resort of each publication, not of the run: it is used for the publication at hand, never kept for the end. Never two publications in parallel, never several in one command (a loop, a script): sites rate-limit or block a burst of requests, the tools' as the browser's, while one publication at a time spreads them out; and after each one you know how many are complete, so you stop at 20.

1. **Parameters**, from the prompt, otherwise by default:

   - `<workdir>`: the curation's root directory.
   - `<run>`: the run's name (`runs.name`), as the user gives it; by default the oldest run with candidates, or with complete publications in its pool.
   - `<pool>`: `<workdir>/run<run>/pool/`, a directory `<pool>/<pmid>/` per publication being downloaded.
   - The candidates, in this order: the pool's publications whose download is not complete, but those closed to which the proxy gives no access, as their line in its status says; then the run's publications `selected` with no AI pass, listed in no `pmids.txt` of the run's batches and not in the pool.

2. **One publication**, the next candidate, taken as far as it can go. One of the pool is taken up where it stopped: from the tools without its manifest, from the browser with it, as `curation-fetch` would rewrite the manifest without the files the browser added.

   1. The tools: `mkdir -p <pool>/<pmid> && uv run curation-fetch <pool>/<pmid> <pmid> > <pool>/<pmid>/fetch.txt`. Read its report, never the full text. Its first line says where the article comes from, ending with `, supplementary files missing: <names>` when some are; without the article, `Full text: closed — <why>`, or `Full text: not downloaded — <why>` when it is free but no copy could be downloaded: fetch once more, as the failure may pass. The manifest, `manifest.json`, is written only when the article could be had.
   2. The browser, its last resort, for what the tools could not download: a free file from the copies the report tried, a closed one through the library proxy (below).
   3. Its line in `<pool>/status.tsv`, written or replaced, tab-separated under a header line: `pmid`; `missing`, empty when its download is complete, else `article` or the names of the missing supplementary files; `tried`, what was tried for them, each with why it failed (fetch: closed, fetch again, browser, proxy: no access).

3. **The next publication**, the same way, until the pool holds 20 complete publications or no candidate is left. A site that starts refusing every request: stop downloading from it; the pool keeps what is done, for the next session.

4. **Batch**: `<batch>`, `<workdir>/run<run>/batch<n>/`, `<n>` the next batch number in the run. Move the complete publications, up to 20, from `<pool>/<pmid>/` to `<batch>/<pmid>/`, remove their lines from `status.tsv`, then write `<batch>/pmids.txt`, one PMID per line, last: a batch with its `pmids.txt` is ready for the `curate` skill.

5. **Reply**: the batch and its publications; the publications left in the pool, each with what is missing and what was tried.

## Browser

When your session has browser tools, the browser is the last resort for the files of the publication at hand that the tools could not download: sites block robots, not a browser. A free article comes only from the copies the fetch report tried, never one declaring a paywall; a closed one only through the library proxy; never a preprint. A page giving only the abstract gives no access. A human check (a captcha) is passed by the user, never by you: ask them.

The browser saves each download in its download folder without asking, a PDF too; ask the user where that folder is when you do not know. It allows one download per page: navigate the tab to each file's URL. A download appears several seconds late, sometimes named `<name> (1).<ext>`: wait before concluding it failed. Move each one at once into `<pool>/<pmid>/`, and leave the folder's other files alone: the article as `<pmid>.pdf`, checked to be the publication (its DOI in its first pages), the supplementary files in `<pmid>.supp/` under their own names, an archive unpacked without its videos. Convert them with `uv run curation-parse <pool>/<pmid> <file>...`, which prints the manifest entries of each file and of its images, and write or complete `manifest.json` (`article`, `supplements` each with its `name`, `figures`, empty for an article had this way). The files the user provides are added the same way.

## Library proxy

A closed file comes through the library proxy, in the browser, once the user has logged it in: `https://doi-org.docelec.univ-lyon1.fr/<doi>` opens the article at its publisher, each host rewritten onto the proxy (`www-sciencedirect-com.docelec.univ-lyon1.fr`). A login page means the session expired: ask the user to log in again, and never enter credentials. A page that asks to buy or to log in through an institution ("Get Access", "does not subscribe") gives no access. The proxy gives none to Springer (its books and Pleiades included), the Nature research journals (`Nat Microbiol`…), the Microbiology Society and Sage (Liebert included): do not try them.

- The article's PDF: navigate the tab to the page's `citation_pdf_url` (ACS, OUP, RSC), or to the publisher's own URL: Wiley `/doi/pdfdirect/<doi>?download=true`, Taylor & Francis `/doi/pdf/<doi>?download=true`, Nature `/articles/<id>.pdf`. LWW only through Ovid: `https://www-ovid-com.docelec.univ-lyon1.fr/jnls/<journal>/fulltext/<doi>`, then its Download PDF link.
- The supplementary files: from the article page's links, each opened in the tab; a file served from another origin (OUP's `oup.silverchair-cdn.com`) by a click on its link. Those that are public come with `curation-download`, without the proxy: Nature's `static-content.springer.com/esm/…`, and ScienceDirect's `https://ars.els-cdn.com/content/image/1-s2.0-<PII>-<mmcN.ext>`, the names from the page's links ending in `-mmc<N>.<ext>`.
- ScienceDirect answers a script with a bot challenge: never script its PDF, never try to pass the challenge. Open the article, `/science/article/pii/<PII>` (its PII in Crossref's `alternative-id`), and click its View PDF button with the mouse, `a.accessbar-utility-component[aria-label^="View PDF"]`, never a View PDF link of the references, which downloads a cited article. The tab it opens passes the check and downloads `1-s2.0-<PII>-main.pdf` (or `-mainext.pdf`); close that tab, as a screenshot times out while it has focus, outside a `browser_batch`. One article about every 40 s: faster, ScienceDirect blocks the session.

# Sample documents

Sample documents for the offshore oil and gas case study in `docs/scenario-offshore-fa.md`. They feed ingestion, chunking, duplicate detection, retrieval, Executor matching and RFP tests.

Every synthetic document is about a fictional operator, "Region South Gas Operator", and its platforms SP-12 and SP-14. All people and companies in them are made up. Each one relates to at least one of three planned Issues:

| `related_issue` | Issue |
|---|---|
| `riser_corrosion_sp12` | External corrosion of gas export riser R-3 in the splash zone |
| `pump_failure_sp12` | Repeated trips of seawater lift pump P-4101A |
| `safety_barrier_gap_sp12` | ESD valve ESDV-1203 closure time and firewater barrier impairment |

## Folders

- `synthetic/`: 22 generated documents (20 DOCX, 2 PDF): 3 inspection reports, 3 shift reports, 5 personnel profiles, 2 project reports, 1 previous issue resolution, 4 Node descriptions, 1 RFP and 3 Proposals.
- `cases/`: 7 variants of other documents that exercise specific cases (see below).
- `public/`: 11 short excerpts of public documents (see below).
- `manifest.csv`: one row per file, with the metadata from spec §7.5 and §7.6.

## Manifest columns

`id, file, format, origin, node, layer, document_type, confidentiality, version, previous_version_id, duplicate_of, related_issue, source_url, license`

- `node` and `layer`: the owning `Node` and its `Layer` (0 National Oil Company, 1 regional operator, 2 platforms, 3 teams, 4 archive).
- `confidentiality`: `public`, `internal` or `confidential`.
- `previous_version_id` and `duplicate_of`: the `id` of another row.
- `related_issue`: Issue slugs separated by `;`. Empty when a public document isn't tied to an Issue.
- `license`: `public-domain-us-gov`, `OGL-3.0`, `CC-BY-4.0` or `CC-BY`. Empty for synthetic documents.
vv
## Test cases

| File in `cases/` | Case | Ground truth |
|---|---|---|
| `cv_moradi_final.docx` | Exact duplicate | Byte-identical to `synthetic/profile_leila_moradi.docx` (`prof-01`) |
| `inspection_sp12_riser_r3_2024.pdf` | Format duplicate | Same content as `synthetic/inspection_sp12_riser_r3_2024.docx` (`ins-01`), as PDF |
| `inspection_sp12_riser_r3_2026_v2.docx` | Version pair | Version 2 of `ins-02-v1`. Adds 3 readings and a change note |
| `shift_report_sp12_2026_09_27.docx` | Partial overlap | Repeats the "Wall loss on riser R-3..." paragraph from `ins-02-v1` word for word |
| `legacy_sp14_pump_overhaul_completion_2019.doc` | Legacy DOC | Word 97-2003 file made with LibreOffice |
| `legacy_riser_ut_inspection_procedure_2017.doc` | Legacy DOC | Word 97-2003 file made with LibreOffice |
| `scanned_sp12_riser_r3_baseline_2021.pdf` | Scanned PDF | One page image, no text layer. Needs the LVM path. Has a table |

Two more cases are in the other folders:

- Real scanned PDF: `public/cullen_piper_alpha_volume2_ch17_excerpt.pdf` is a 1990 scan with no text layer.
- Proposal quality: in `synthetic/`, `proposal_meridian_rotating_integrity.pdf` is strong and meets all mandatory requirements in the RFP. `proposal_coastline_engineering.docx` is middling: it has no metallurgical lab, no CVs and a vague schedule. `proposal_quickfix_pump_services.docx` is weak: it skips the analysis and breaks the offline data rule (M4).

## Regenerate

Run from the repository root:

```bash
uv run --with python-docx --with reportlab --with pypdf python scripts/build_fixtures.py
```

The script rewrites `synthetic/`, `cases/` and the synthetic rows of `manifest.csv`. It keeps the public rows and never touches `public/`. Running it again gives byte-identical files, except the `.doc` files. The `.doc` files need LibreOffice (`soffice`). Without it they are skipped with a warning.

## Public documents

The licence of each document was checked on its source page before download:

| File | Source | Licence | How it was checked |
|---|---|---|---|
| `bsee_safety_alert_518/519/524_*.pdf` | BSEE Safety Alerts 518, 519 and 524, all pages | US federal work, public domain | bsee.gov/disclaimer: "public information and may be distributed or copied" |
| `hse_safety_bulletin_*.pdf` (3) | UK HSE bulletins CEMHD1-2023, ED02-2026, ED09-2023 | OGL v3.0 | hse.gov.uk footer and copyright page |
| `csb_macondo_executive_summary_excerpt.pdf` | CSB Macondo report, Executive Summary pages 6-10 | US federal work, public domain | csb.gov/privacy-policy: "public information that may be distributed or copied" |
| `cullen_piper_alpha_volume2_ch17_excerpt.pdf` | Cullen report (Cm 1310) Volume 2, PDF pages 28-30, start of Chapter 17 "Safety Assessment" | OGL v3.0 (Crown copyright) | Hosted on hse.gov.uk, whose footer says all content is OGL v3.0 unless stated otherwise. No other licence is stated |
| `scirep_2024_*_excerpt.pdf` | Sci. Rep. 2024, doi:10.1038/s41598-024-67463-2, pages 1-3 | CC BY 4.0 | Licence statement in the PDF and Europe PMC |
| `plosone_2026_*_excerpt.pdf` | PLOS ONE 2026, doi:10.1371/journal.pone.0353469, pages 1-3 | CC BY | Licence statement in the PDF and Europe PMC |
| `fmicb_2026_*_excerpt.pdf` | Front. Microbiol. 2026, doi:10.3389/fmicb.2026.1908395, pages 1-3 | CC BY | Licence statement in the PDF and Europe PMC |

The HSE bulletins are web pages only. Their main text was extracted and written to a plain PDF with a source and OGL attribution line. Images and navigation were dropped.

### How they were fetched

This was done by hand once, not by a script. Full downloads go in `data/raw/`, which is gitignored. Treat them as untrusted and never run anything from them.

```bash
mkdir -p data/raw/{bsee,csb,piper_alpha,papers}
B=https://www.bsee.gov/sites/bsee.gov/files
curl -L -o data/raw/bsee/bsee_alert_518_lact_pump_fire.pdf "$B/2026-07/BSEE%20Safety%20Alert%20518%20-%20Mechanical%20Failure%20of%20LACT%20Pump%20Causes%20Fire_June%202026_v1.0.pdf"
curl -L -o data/raw/bsee/bsee_alert_519_riser_fin_retention.pdf "$B/2026-07/BSEE%20Safety%20Alert%20519%20-%20Verify%20Riser%20Fin%20Retention%20Systems%20Before%20Prompts%20Riser%20Handling%20Operations_June%202026_v1.0.pdf"
curl -L -o data/raw/bsee/bsee_alert_524_production_safety_training.pdf "$B/2026-08/MMA%20Safety%20Alert%20524-%20Improvements%20Needed%20In%20Production%20Safety%20System%20Training.pdf"
curl -L -o data/raw/csb/csb_macondo_exec_summary.pdf "https://www.csb.gov/assets/1/20/20160412_Macondo_Full_Exec_Summary.pdf"
curl -L -o data/raw/piper_alpha/piper_alpha_public_inquiry_volume2.pdf "https://www.hse.gov.uk/offshore/assets/docs/piper-alpha-public-inquiry-volume2.pdf"
curl -L -o data/raw/papers/scirep_2024_offshore_pipeline_external_corrosion.pdf "https://www.nature.com/articles/s41598-024-67463-2.pdf"
curl -L -o data/raw/papers/plosone_2026_ultrasonic_pipe_corrosion.pdf "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0353469&type=printable"
curl -L -o data/raw/papers/fmicb_2026_mic_offshore_infrastructure.pdf "https://www.frontiersin.org/articles/10.3389/fmicb.2026.1908395/pdf"
```

Excerpts were cut with `qpdf`, for example:

```bash
qpdf --empty --pages data/raw/csb/csb_macondo_exec_summary.pdf 6-10 -- fixtures/docs/public/csb_macondo_executive_summary_excerpt.pdf
```

The HSE bulletin pages were saved with `curl` from `https://www.hse.gov.uk/safetybulletins/<name>.htm`. The text inside `<main>` (headings, paragraphs, list items) was written to PDF with reportlab.

### To fetch manually

- Montara Commission of Inquiry report (2010). Source pages: https://consult.industry.gov.au/montara-commission-of-inquiry (needs JavaScript) and https://nla.gov.au/nla.obj-961839109 (blocks automated access). No licence could be checked, so it was skipped.
- More CC-BY papers on riser corrosion. MDPI, Springer and Europe PMC PDF links block automated downloads. Candidates with CC BY in Europe PMC metadata: doi:10.3390/ma12091520 (X80 riser steel corrosion fatigue) and doi:10.3390/ma19061047 (X70 pipeline steel in seawater).

## Gaps

- Legacy `.doc` files are converted from DOCX by LibreOffice. They are not real old Word files, so they won't have quirks such as fast-save fragments.
- The synthetic scanned PDF is a clean render with light noise and a 0.7 degree skew. It is easier to read than a real scan. The Cullen excerpt is the harder, real case.
- Partial overlap is recorded only in this README. `manifest.csv` has no column for it.
- The PLOS ONE and Frontiers PDFs say "Creative Commons Attribution License" without a version, so their licence is recorded as `CC-BY`.

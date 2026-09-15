# Korean regression comparison

`prepare_regression_v2.hwf` (run configuration `llm-local`) freezes the existing 20
`ko-v1` evaluation postings plus the two explicit-duty postings into
`korean-regression-v2-22`. It verifies all 22 source hashes and the pinned JOB-ALIO
and NCS snapshots. It then imports the accompanying reference assertions through
the existing native JSON/Hop importer. It makes no model requests. Repeating it
preserves the cases and appends an identical assertion revision.

These are **provisional assistant-authored source assertions, not human gold**.
They were written before the new DeepSeek/Luna outputs. This is a regression set
whose earlier DeepSeek failures informed `ko-v2`, not a held-out benchmark. There
are 32 requirement assertions and four duty assertions. Requirements are not
exhaustively labelled, so requirement precision cannot be calculated. The 20
postings without explicit duties have complete empty duty/NCS labels; the two
duty-bearing postings have partial duty labels and no authoritative NCS labels.
Review new positive NCS matches against the actual definitions separately.

`check_logic=false` means that assertion checks the fact/category/kind but does
not distinguish a single textual condition from an equivalent expression tree.
Explicit alternatives use the normal logic check. References with `kind` check
eligibility/preference/exclusion/unrestricted meaning, and optional
`position_names` can constrain the complete position set. `ko-v2` label matching
requires the label text to occur in the extracted text, not just somewhere in a
larger evidence quotation. The 32 assertions are a partial coverage measure;
they do not prove complete semantic accuracy, even at 100%.

Run both models with the same dataset, `PROMPT_VERSION=ko-v3`, `REUSE_CACHE=N`,
`ACCEPTANCE_POLICY=REVIEW`, and the same limits. Use separate batches and provider
selections. Luna's endpoint does not advertise temperature support, so leave
`TEMPERATURE` blank. Record reasoning settings and providers in the comparison.
Never feed labels to either model. Batch/result views expose validated evidence,
issues, costs and assertion scores. `enrichment.attempt` separately retains raw
responses, including rejected objects that the result view excludes.

The manifest and assertion files contain public posting identifiers and short
source excerpts. Credentials and full runtime data remain on Goldship.

The dataset ID's `v2` names the frozen sample, independently of the prompt version.
Both `ko-v2` and the corrected fragment-based `ko-v3` are compared on these exact
same sources and prewritten assertions. Earlier runs are retained unchanged.
The intermediate `ko-v2` responses informed the `ko-v3` contract and prompt; this
sample therefore cannot measure generalization to unseen postings. See the
[comparison report](../../../docs/hop-migration/llm-model-comparison-2026-09-12.md)
for batch IDs, parameters, costs and case observations.

## Attachment source assertions

`attachment-pilot-v1.assertions.json` contains eight partial assistant-authored
assertions bound to verified document hashes, section locators and exact Unicode
code-point offsets. They cover conjunctions, conditional duties, actual versus
example NCS references, unversioned references, age-limit qualifiers, conditional
permission and an explicitly undeveloped clinical classification.

These are future attachment-aware regression inputs, not human gold or accepted
production claims. The existing inline-only evaluation importer does not accept
this separate contract. Keep the assertions out of model prompts. Their source
receipts and remaining input-contract work are recorded in the
[completion ledger](../../../docs/hop-migration/ontology-completion.md#native-attachment-ingestion--2026-09-12).

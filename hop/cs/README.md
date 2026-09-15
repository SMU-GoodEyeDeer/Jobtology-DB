# Common posting input and current handoff

Install `sql/001_common_postings.sql` after the ingestion schema and
`hop/llm/sql/021_link_publication.sql`. It adds `cs.common_posting` and does not
rewrite ALIO records, bundles, model attempts, review decisions or graph nodes.
The ALIO adapter keeps the existing native `posting_id`, graph identity
`job-alio:posting:<id>`, inline source hash, and attachment-aware
`enrichment.linking_input_hash` as its `content_hash`. Use
`cs.posting_work_lineage` to find saved items/revisions by that exact hash; a
missing current match can still have older attempts under a changed source hash.

For a later provider, create a `cs.source_snapshot` row in `LOADING`, insert
normalized `cs.posting_input` rows with the provider's original posting ID,
title, source fields and evidence references, then mark the snapshot `READY`
with `completed_at`. `cs.common_posting` only exposes READY rows. Its
`source_id` plus `source_posting_id` retain provenance; the derived `posting_id`
and `posting_identity` include a provider-specific digest so another provider's
native ID cannot collide. Pin `snapshot_run_id` when assessing a corpus.

The common view supports source-independent **selection and reporting** now.
The existing `enrichment.plan_batch`, document preparer, current linking status
and Neo4j publication paths still select `job_alio` snapshots. They need
provider adapters before generic rows can be extracted, reviewed or published.
The compatibility bridge preserves ALIO's prior review lineage while those
consumers are extended; it does not grant a generic row an ALIO review.

For reviewed ALIO positions with a current explicit duty but no NCS match,
use the native, no-model [manual NCS review](MANUAL_NCS_REVIEW.md) workflows.

The [qualification support policy](sql/006_qualification_support.sql) installs
with `cs/install.hwf` after `docs/hop-migration/reference-support.sql`. It keeps
the original 11 NCS qualification occupations enabled and adds only the 11
category-20 occupations represented by currently accepted in-scope CS links.
Older qualification runs retain their original partitions; new runs pin the
enabled occupation codes in `settings.qualification_scope_codes`. Run
`ingestions/ncs_qualification/full.hwf` for the expanded qualification mapping
and then refresh Q-Net exam sessions for any newly mapped credentials. The
`ingestion.related_qualification_report` result distinguishes fetched-empty
from unfetched mappings and describes related qualifications, not employer
requirements.

Run `read_qualification.hwf` for the current accepted, IN_SCOPE position links
and their related credential/exam statuses. It defaults to NCS category 20; set
`TECHNICAL_ONLY=N` to include accepted links from other NCS categories. Use
`POSTING_IDENTITY` to inspect an exact source-qualified posting. The companion
`read_qualification_summary.hwf` groups coverage and explicit mapping/exam gaps
by advertised position. Set the exact `POSTING_IDENTITY` before either read; a
blank identity returns no rows. The corpus-wide SQL view currently exceeds a
two-minute scan budget, so use the filtered native readers for routine review.
Both workflows read the latest READY qualification and Q-Net runs and make no
API or model request. `sql/007_qualification_status.sql`
installs their views through the SQL-only `install_qualification_status.hwf`.

Run `python hop/cs/tests/common_postings.py` for a disposable PostgreSQL test
of ALIO lineage, same-native-ID collisions across providers, READY gating,
scope/report installation and replay. It makes no model requests.

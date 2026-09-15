# Review a batch of advertised IT/AI/data positions

Install `cs/sql/001_common_postings.sql` through `004_scope_packets.sql` with
`cs/install.hwf`. If `001`–`003` are already installed, run
`cs/install_scope_review.hwf` to add only `004`. The SQL modules add the scope
read views and native JSON review transport. They do not call an LLM or
publish any graph relationship.

Run `cs/export_scope_review.hwf` with `ACTOR` set to the operator preparing
the file. `SCOPE_STATUS=NEEDS_REVIEW` is the default; set `SOURCE_ID` to a
specific provider or leave it blank for all current providers. The selected
positions must fit `POSITION_LIMIT` (1–1000). `REVIEW_FILE` must be a new
path; Hop refuses to overwrite an existing packet.

On an existing project, run `cs/install_scope_policy.hwf` after deploying a
new `002_scope.sql`. The scope input uses the latest **accepted** extraction
revision for each current source hash. A pending or rejected correction remains
in the review history and cannot silently replace the accepted roster. Accepting
a corrected revision changes role bindings; export a new scope packet and review
those roles against the corrected source before counting their links.

For a larger source, use `cs/read_scope.hwf` to obtain source-qualified
`posting_identity` values, then set `POSTING_IDENTITIES` to a `|`-separated
list for each review batch. All roles in the named postings are exported;
split the list until each packet fits `POSITION_LIMIT`.

The generated JSON contains each position's source-qualified posting ID,
current source snapshot, source/content hash, advertised role, role duties,
evidence, screening signals and expected latest decision. These are frozen
context fields. Edit only the top-level `reviewer` and `reviewer_kind`, and
each case's `decision`, `family` and `notes`:

- `decision`: `IN_SCOPE`, `OUT_OF_SCOPE`, `NEEDS_REVIEW`, or JSON `null` to
  leave that case pending.
- `family`: `SOFTWARE`, `IT_SYSTEMS`, `SECURITY`, `DATA` or `AI` for
  `IN_SCOPE`; JSON `null` for the other decisions. Pick the primary family.
- `notes`: a nonblank explanation grounded in the advertised position and
  duties for every explicit decision.

Set `reviewer` to the actual reviewer and `reviewer_kind` to `human`,
`assistant` or `policy`. Import the completed file with
`cs/import_scope_review.hwf`. PostgreSQL validates the entire packet against
the current source and role context before saving decisions. One edited or
stale case rejects the whole import. Exact replay returns the same immutable
receipt without duplicate decisions. A new packet with identical latest
decisions also leaves the decision table unchanged.

After import, run `cs/assess.hwf` or `cs/read_scope.hwf` to inspect which
positions are in scope and what saved NCS work remains. Importing this review
does not by itself approve extraction or NCS links.

The disposable contract check is `python hop/cs/tests/scope_packets.py`.

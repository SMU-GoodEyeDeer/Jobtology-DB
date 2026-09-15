# Manual, position-specific NCS candidates in Hop

Use this path when an accepted CS position has an explicit duty but no supported NCS link from the saved model shortlist. It searches no external service and makes no model call. The reviewer must compare that duty with the **complete current NCS unit definition**, including its occupation context. Shared keywords or a job title alone are insufficient.

Run `cs/install_manual_ncs_review.hwf` once after the ordinary CS and LLM SQL installers. The regular `cs/install.hwf` also includes `005_manual_ncs_links.sql` when installing a new CS project. Both are safe to rerun; they leave previous candidates, decisions and import receipts intact.

1. Run `cs/read_scope.hwf` with `SCOPE_STATUS=IN_SCOPE` and identify the exact source-qualified `posting_identity` and `role_id`. Check `cs/assess.hwf` for the position's current link count. Inspect the accepted extraction duties and current NCS catalog before choosing pairs. Duty indices are zero-based and **must have that role ID in `position_ids`**.
2. Write a UTF-8 selection file such as `${PROJECT_HOME}/data/cs/manual-ncs-selection.json`:

   ```json
   {
     "selections": [
       {
         "posting_identity": "job-alio:posting:304432",
         "role_id": "p4",
         "duty_index": 21,
         "competency_code": "2001020214_23v6"
       }
     ]
   }
   ```

   Up to 100 distinct duty/code choices can be in one file. There is no implicit match acceptance.
3. Run `cs/export_manual_ncs_review.hwf` with `SELECTION_FILE`, a named `ACTOR`, and a new `REVIEW_FILE`. The workflow checks each current role and writes a packet without overwriting an existing file. If the accepted extraction batch pins an older NCS run, export fails; obtain a current-catalog extraction/batch before proposing a new link.
4. Review each packet case. Its `context` freezes the source data and hash, accepted extraction revision, role binding, exact duty, latest NCS run, full unit definition and occupation. Set top-level `reviewer` and `reviewer_kind` (`human` or `assistant`). For each supported pair set `decision` to `ACCEPT`; for an unsupported pair set `REJECT`. Every decided case needs a source-and-definition-grounded `reason` and review `notes`. Leave an undecided case as `null`.
5. Save the completed packet under a new filename and run `cs/import_manual_ncs_review.hwf` with `REVIEW_FILE`. PostgreSQL validates **all** frozen cases before writing any link candidate or decision. A corrected role, changed source input, newer NCS run, changed catalog row or edited packet context rejects the entire import. Import is append-only; exact replay and identical fresh decisions do not duplicate records. An already existing model candidate for the same revision/code/duty must be reviewed through `llm/export_link_review.hwf` and `llm/import_link_review.hwf` instead.
6. Recheck `cs/assess.hwf`. Only an accepted candidate linked to the selected position's explicit duty counts as its NCS coverage. Run `llm/publish_links.hwf` separately to publish reviewed PostgreSQL links to Neo4j. The manual import itself does not update the graph.

This workflow currently operates on ALIO enrichment revisions. `cs.common_posting` supports selection and reporting for future sources, but their extraction, catalog pinning and graph publication adapters are still to be implemented.

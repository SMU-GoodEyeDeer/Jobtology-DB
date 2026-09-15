"""Independent extraction/link decisions, native correction import and temporal safety."""
import copy
import json


def check_review(sql, js, q, run_hop, params, cmd, hop, remote, work):
    run_hop('enrich.hwf', params | dict(PROMPT_VERSION='ko-v4', REUSE_CACHE='N'), 'independent-review-enrich')
    bid = sql("SELECT batch_id FROM enrichment.batch WHERE mode='ENRICH' ORDER BY created_at DESC LIMIT 1")
    item = sql(f"SELECT item_id FROM enrichment.item WHERE batch_id={q(bid)} AND posting_id='001'")
    before = sql(f"SELECT to_jsonb(a)::text FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.item_id={q(item)}")
    p = dict(ITEM_ID=item, ACTOR='synthetic-review-agent', REASON='Fixture capture')
    run_hop('capture_extraction.hwf', p, 'capture-independent-extraction')
    revision = sql(f"SELECT revision_id FROM enrichment.extraction_revision WHERE item_id={q(item)}")
    run_hop('capture_extraction.hwf', p, 'repeat-independent-capture')
    assert sql(f"SELECT count(*) FROM enrichment.extraction_revision WHERE item_id={q(item)}") == '1'
    decision = dict(REVISION_ID=revision, DECISION='ACCEPT', REVIEWER='fixture-reviewer',
        REVIEWER_KIND='assistant', NOTES='Synthetic source and extraction checked')
    run_hop('review_extraction.hwf', decision, 'accept-independent-extraction')
    assert sql("SELECT decision='ACCEPT' AND extraction IS NOT NULL AND reviewed_ncs_links='[]' FROM enrichment.current_reviewed_posting WHERE posting_id='001'") == 't'
    run_hop('import_model_links.hwf', dict(REVISION_ID=revision, ACTOR='fixture-import'), 'import-independent-links')
    candidate = sql(f"SELECT candidate_id FROM enrichment.link_candidate WHERE revision_id={q(revision)}")
    link_decision = dict(CANDIDATE_ID=candidate, DECISION='REJECT', REVIEWER='fixture-reviewer',
        REVIEWER_KIND='assistant', NOTES='Synthetic rejected link')
    run_hop('review_link.hwf', link_decision, 'reject-independent-link')
    assert sql("SELECT decision='ACCEPT' AND extraction IS NOT NULL AND reviewed_ncs_links='[]' FROM enrichment.current_reviewed_posting WHERE posting_id='001'") == 't'
    run_hop('review_link.hwf', link_decision | dict(DECISION='ACCEPT', NOTES='Synthetic source and target definition checked'), 'accept-independent-link')
    assert sql("SELECT jsonb_array_length(reviewed_ncs_links) FROM enrichment.current_reviewed_posting WHERE posting_id='001'") == '1'
    # A newer NCS source invalidates links, while content-matching extraction survives.
    output = sql("""BEGIN; INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state)
VALUES('review-new-ncs','ncs_competency','FULL','test','READY');
SELECT extraction IS NOT NULL AND reviewed_ncs_links='[]' FROM enrichment.current_reviewed_posting WHERE posting_id='001'; ROLLBACK;""")
    assert 't' in output.splitlines(), output
    run_hop('review_extraction.hwf', decision | dict(DECISION='REJECT', NOTES='Synthetic revocation'), 'revoke-independent-extraction')
    assert sql("SELECT extraction IS NULL AND reviewed_ncs_links='[]' FROM enrichment.current_reviewed_posting WHERE posting_id='001'") == 't'
    run_hop('review_extraction.hwf', decision, 'restore-independent-extraction')
    raw = json.loads(sql(f"SELECT raw_output FROM enrichment.extraction_revision WHERE revision_id={q(revision)}"))
    corrected = copy.deepcopy(raw)
    corrected['duties'][0]['text_parts'] = ['데이터베이스 설계']
    package = dict(item_id=item, parent_revision_id=revision, actor='fixture-corrector',
        reason='Synthetic narrower explicit duty', output=corrected)
    path = work / 'correction.json'; path.write_text(json.dumps(package, ensure_ascii=False))
    cmd(['docker', 'cp', str(path), hop + ':' + remote + '/correction.json'])
    run_hop('import_correction.hwf', dict(CORRECTION_FILE=remote+'/correction.json'), 'import-independent-correction')
    new = sql(f"SELECT revision_id FROM enrichment.extraction_revision WHERE item_id={q(item)} ORDER BY revision_no DESC LIMIT 1")
    assert new != revision
    assert sql("SELECT extraction IS NULL AND decision IS NULL AND reviewed_ncs_links='[]' FROM enrichment.current_reviewed_posting WHERE posting_id='001'") == 't'
    try:
        sql(f"SELECT enrichment.import_model_links({q(new)},'tester')")
        raise AssertionError('Reused indices after changing duties')
    except RuntimeError as e: assert 'DUTIES_CHANGED_RECATEGORIZE' in str(e), str(e)
    eval_item = sql("SELECT item_id FROM enrichment.result WHERE mode='EVAL' AND state='VALIDATED' LIMIT 1")
    try:
        sql(f"SELECT enrichment.capture_extraction({q(eval_item)},'tester','Must not publish eval')")
        raise AssertionError('EVAL entered production review')
    except RuntimeError as e: assert 'EVAL_CANNOT_ENTER_PRODUCTION_REVIEW' in str(e), str(e)
    for query in [f"UPDATE enrichment.extraction_revision SET actor='rewrite' WHERE revision_id={q(revision)}",
        f"DELETE FROM enrichment.link_decision WHERE candidate_id={q(candidate)}"]:
        try: sql(query); raise AssertionError('Review history mutated')
        except RuntimeError as e: assert 'APPEND_ONLY_REVIEW_HISTORY' in str(e), str(e)
    after = sql(f"SELECT to_jsonb(a)::text FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.item_id={q(item)}")
    assert after == before, 'Correction rewrote original provider attempt'
    assert sql(f"SELECT count(*) FROM enrichment.review WHERE item_id={q(item)}") == '0', 'Independent review impersonated legacy whole-item acceptance'
    print('Native independent extraction/link review, replay, corrections, revocation, NCS freshness and append-only audit passed', flush=True)

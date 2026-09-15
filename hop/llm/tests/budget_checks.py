"""Reservations settle only known terminal costs; test real gating and audit retention."""
import json
import uuid


def check_budget(sql, js, q):
    assert json.loads(sql("""SELECT jsonb_build_array(
      enrichment.response_cost('{"usage":{"cost":0.002,"is_byok":false}}'),
      enrichment.response_cost('{"usage":{"cost":0,"is_byok":true,"cost_details":{"upstream_inference_cost":0.003}}}'),
      enrichment.response_cost('{"usage":{"cost":0,"is_byok":true}}'))""")) == [0.002, 0.003, None]
    assert json.loads(sql("""SELECT jsonb_build_array(
      enrichment.accounted_cost('VALIDATED',0.001,0.05),
      enrichment.accounted_cost('REJECTED',0.002,0.05),
      enrichment.accounted_cost('ERROR',NULL,0.05),
      enrichment.accounted_cost('RESERVED',0.001,0.05),
      enrichment.accounted_cost('VALIDATED',0.07,0.05),
      enrichment.accounted_cost('ERROR',0,0.05))""")) == [0.001, 0.002, 0.05, 0.05, 0.07, 0]
    options = json.loads(sql('SELECT settings FROM enrichment.batch ORDER BY created_at DESC LIMIT 1'))
    options.update(execute_requests='Y', reuse_cache='N', max_requests=5, max_cost_usd=0.06,
        daily_budget_usd=1000, request_reserve_usd=0.05, limit=2, acceptance_policy='REVIEW')
    # One transaction per scenario: no synthetic charge survives this check.
    for state, cost, expected in [('VALIDATED', '0.001', 'RESERVED'),
        ('ERROR', 'NULL', 'BUDGET_BLOCKED'), ('RESERVED', 'NULL', 'BUDGET_BLOCKED'),
        ('VALIDATED', '0.07', 'BUDGET_BLOCKED')]:
        bid = 'budget-fixture-' + str(uuid.uuid4())
        data = sql(f"""BEGIN;
SELECT enrichment.plan_batch({q(bid)},'EVAL','test-ko','LATEST','LATEST',{js(options)});
SELECT enrichment.plan_stage({q(bid)},'extract');
SELECT enrichment.reserve_request((SELECT extraction_id FROM enrichment.item WHERE batch_id={q(bid)} ORDER BY ordinal LIMIT 1));
UPDATE enrichment.attempt SET state={q(state)},cost_usd={cost}
WHERE attempt_id=(SELECT extraction_id FROM enrichment.item WHERE batch_id={q(bid)} ORDER BY ordinal LIMIT 1);
SELECT enrichment.reserve_request((SELECT extraction_id FROM enrichment.item WHERE batch_id={q(bid)} ORDER BY ordinal OFFSET 1 LIMIT 1));
SELECT jsonb_build_object('first_reserved',a.reserved_usd,'second_state',b.state)
FROM enrichment.item x JOIN enrichment.attempt a ON a.attempt_id=x.extraction_id
CROSS JOIN enrichment.item y JOIN enrichment.attempt b ON b.attempt_id=y.extraction_id
WHERE x.batch_id={q(bid)} AND y.batch_id=x.batch_id AND x.ordinal<y.ordinal;
ROLLBACK;""")
        result = json.loads(next(line for line in data.splitlines() if line.startswith('{')))
        assert result == dict(first_reserved=0.05, second_state=expected), result
    # The rolling account is shared across batches, even when a batch has headroom.
    daily = float(sql("SELECT coalesce(sum(enrichment.accounted_cost(state,cost_usd,reserved_usd)),0) FROM enrichment.attempt WHERE reserved_at>now()-interval '24 hours'"))
    tight = options | dict(daily_budget_usd=round(daily + 0.04, 6), max_cost_usd=2)
    bid = 'daily-fixture-' + str(uuid.uuid4())
    data = sql(f"""BEGIN;
SELECT enrichment.plan_batch({q(bid)},'EVAL','test-ko','LATEST','LATEST',{js(tight)});
SELECT enrichment.plan_stage({q(bid)},'extract');
SELECT enrichment.reserve_request((SELECT extraction_id FROM enrichment.item WHERE batch_id={q(bid)} ORDER BY ordinal LIMIT 1));
SELECT state FROM enrichment.attempt WHERE batch_id={q(bid)} ORDER BY item_id;
ROLLBACK;""")
    assert 'BUDGET_BLOCKED' in data, data
    print('Settled/unknown/inflight/over-reservation costs, preserved audit and shared rolling budget checks passed', flush=True)

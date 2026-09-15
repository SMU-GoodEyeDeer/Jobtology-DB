-- Frozen regression inputs; no model calls or source changes.
-- Reference assertions are assistant-authored and provisional, not human gold.
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('llm-dataset:korean-regression-v2-22',0));
SELECT enrichment.assert_snapshot('77ccb77b-3afc-4965-8ce5-efd687304954','job_alio');
SELECT enrichment.assert_snapshot('a32170ed-7485-4e31-82d3-ed48b3398946','ncs_competency');
CREATE TEMP TABLE v2_expected(ordinal integer,posting_id text,source_hash text) ON COMMIT DROP;
INSERT INTO v2_expected VALUES
(1,'304450','2ee9ebbe8f7fb9286e260fa96a355bf6ce44d46d1f2ec88bbc1dfe6a403e62b1'),
(2,'304648','3583e95c158fc4cbea5de5ef3f28fdba82828e4a6869d362feaf818ab11712f1'),
(3,'304574','e84c3a41a65a1583f60f71f3f01c6c47adba9fadc2485a22bf5cc1078c4d545e'),
(4,'298713','c1e24dd284ad0027873c1ad25d92dcfafac1e53ea4a01a38c5d44e2b180790c1'),
(5,'304237','d0f3d6fc32620d969de60933087c3061c7a85185b0e63501d926e94ab1d0b863'),
(6,'304400','d0f1f9ae177bb769b1daa517778daf5800bb50ed0f50d7e196c40cf526c03be2'),
(7,'304630','8be40619fa9b0197453bc463d446cbdde98c709bf827321981976acd832ce99b'),
(8,'300965','dc4f97253611f131b9655ba9d42be75bb9ed88905f31d24d96f7fd10e04efad9'),
(9,'304717','e4c48b005bc12ec46ae16d4884fd17f02003bcdc1f82ea02ad79a6a2b95d8845'),
(10,'304830','ddbade59b63038e14f1d6736b4ae6159b7f76e540f2a6b1a6b4de0365b954ec2'),
(11,'304846','3405bf7a718fd36b763e7f2f13ca91fdc31b65cc44a1ec59c868d1616863fb06'),
(12,'304676','66bc0101015737eca6d29d31e82dcc927d3541743024ac7169ed3c344f9b7107'),
(13,'299690','8e1a3076cd29858eb1476957159c84ffe8f38e5036e0da5e7144d1fdba696f92'),
(14,'304445','07b79668da8874d9f2f03c5c6cf00ca537bd8a3abc6fd78f34fb3e12deddd1f9'),
(15,'304741','23b3046b71674f376973464f4a32ebef7ba6e836ec097410a9e039998c19b7ef'),
(16,'304660','ecc7a3eea44ffcd23443b3ceaacec77ab93b5fc4cb6544a6a8616d5d940a91ec'),
(17,'304844','07d9450ef3b49997974c0b21de08ed8a4670f27a61232d828768f60be80e4b13'),
(18,'304165','b0f9f9923650b5f5f51f5ff180968d984322e92cafd8c30ebae6fe64b4e33e4e'),
(19,'295717','6397b5967dfe9cd74e3e75b601bb706ee3da754dded324ab229ee0d5b221c56c'),
(20,'304739','c2f243e032612ee65f628877e30121272d030515b984e7d3f233d4a458f2ad87'),
(21,'304435','c5bcc2b97cb9ddc37040cf0991873c56c6de23bef5ce219928ffae2faacc92ef'),
(22,'304602','8c41636a0a6cc3680fecf8aff99ea1ad1f28ec29a34a1612db5fb52b5224142d');
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM v2_expected e LEFT JOIN ingestion.job_posting p
  ON p.run_id='77ccb77b-3afc-4965-8ce5-efd687304954' AND p.posting_id=e.posting_id
  WHERE p.posting_id IS NULL OR enrichment.hash(enrichment.source_fields(p.normalized)::text)<>e.source_hash)
 THEN RAISE EXCEPTION 'REGRESSION_SOURCE_HASH_MISMATCH'; END IF;
END $$;
INSERT INTO enrichment.dataset(dataset_id,job_run_id,ncs_run_id,seed,requested_size)
VALUES('korean-regression-v2-22','77ccb77b-3afc-4965-8ce5-efd687304954','a32170ed-7485-4e31-82d3-ed48b3398946','existing-20-plus-2-explicit-duties',22) ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM enrichment.dataset WHERE dataset_id='korean-regression-v2-22'
  AND job_run_id='77ccb77b-3afc-4965-8ce5-efd687304954' AND ncs_run_id='a32170ed-7485-4e31-82d3-ed48b3398946' AND requested_size=22 AND seed='existing-20-plus-2-explicit-duties')
 THEN RAISE EXCEPTION 'REGRESSION_DATASET_ALREADY_DIFFERS'; END IF;
END $$;
INSERT INTO enrichment.test_case(dataset_id,posting_id,source_data,source_hash,stratum,ordinal)
SELECT 'korean-regression-v2-22',e.posting_id,enrichment.source_fields(p.normalized),e.source_hash,
 CASE WHEN e.ordinal<=20 THEN 'previous-regression' ELSE 'explicit-duties' END,e.ordinal
FROM v2_expected e JOIN ingestion.job_posting p ON p.posting_id=e.posting_id AND p.run_id='77ccb77b-3afc-4965-8ce5-efd687304954'
ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF (SELECT count(*) FROM enrichment.test_case WHERE dataset_id='korean-regression-v2-22')<>22 OR EXISTS(
  SELECT 1 FROM v2_expected e LEFT JOIN enrichment.test_case c ON c.dataset_id='korean-regression-v2-22' AND c.posting_id=e.posting_id
  WHERE c.posting_id IS NULL OR c.ordinal<>e.ordinal OR c.source_hash<>e.source_hash
   OR enrichment.hash(c.source_data::text)<>e.source_hash)
 THEN RAISE EXCEPTION 'REGRESSION_CASES_ALREADY_DIFFER'; END IF;
END $$;
COMMIT;

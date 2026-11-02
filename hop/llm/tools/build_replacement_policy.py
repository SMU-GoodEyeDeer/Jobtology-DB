"""Generate the frozen replacement policy from embedded and canonical SQL.

SQL literals retain their qualified formatting so regeneration stays byte exact.
"""

# Embedded SQL and its replacement strings preserve qualified artifact bytes.
# ruff: noqa: E501

import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
core=r'''-- New-cohort automated exclusion only. Technical responses/review/accounting stay exact.
BEGIN;
SELECT retention.gate();
CREATE SCHEMA IF NOT EXISTS replacement_matching;
CREATE OR REPLACE FUNCTION replacement_matching.field_text(fields jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
 SELECT lower(coalesce(string_agg(CASE WHEN key='title' THEN regexp_replace(value#>>'{}','^([[:space:]]*(\[[^]]*\]|\([^)]*\)))+[[:space:]]*','','g') ELSE value#>>'{}' END,' ' ORDER BY key),'')) FROM jsonb_each(fields)
 WHERE key IN('title','role','job_position_raw') AND jsonb_typeof(value)='string'
$$;
CREATE OR REPLACE FUNCTION replacement_matching.supported(scheme text,code text,source text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce((SELECT NOT EXISTS(SELECT 1 FROM unnest(patterns) p WHERE source !~ p)
 FROM (VALUES
('NCS','19030603',ARRAY['반도체','장비|설비|(?<![a-z])hardware(?![a-z])|fse|field.service|진공|plasma|e.beam']::text[]),
('NCS','20010215',ARRAY['클라우드|(?<![a-z])cloud(?![a-z])|(?<![a-z])aws(?![a-z])|(?<![a-z])azure(?![a-z])|(?<![a-z])gcp(?![a-z])','엔지니어|engineer|인프라|운영|devops']::text[]),
('NCS','20010206',ARRAY['보안|security','엔지니어|engineer|설계|개발']::text[]),
('NCS','20010301',ARRAY['전산|시스템|서버|네트웍|(?<![a-z])network(?![a-z])|(?<![a-z])dba(?![a-z])|devops|sre|포탈|포털|it.manager','운영|관리|모니터|monitor|유지보수|manager|devops|sre|administrator|(?<![a-z])dba(?![a-z])']::text[]),
('NCS','20010105',ARRAY['data.scientist|사이언티스트|데이터.?과학|(데이터|data).{0,12}(분석|analyst)']::text[]),
('NCS','19031802',ARRAY['자율주행|autonomous','개발|소프트웨어|(?<![a-z])sw(?![a-z])|s/w|(?<![a-z])software(?![a-z])']::text[]),
('NCS','20010501',ARRAY['보안|소프트웨어|클라우드|솔루션|(^|[^a-z])(it|ax|(?<![a-z])ai(?![a-z])|(?<![a-z])erp(?![a-z])|sap)([^a-z]|$)','영업|sales']::text[]),
('NCS','20010605',ARRAY['컴퓨터.?비전|computer.?vision|영상.?처리|영상정보처리']::text[]),
('NCS','20010201',ARRAY['(?<![a-z])sw(?![a-z])|소프트웨어|(?<![a-z])software(?![a-z])','아키텍|architect|아키텍쳐']::text[]),
('NCS','20010202',ARRAY['웹|앱|응용|백엔드|프론트|풀스택|frontend|front.end|backend|back.end|full.stack|application|(?<![a-z])java(?![a-z])|(?<![a-z])python(?![a-z])|\.net|(?<![a-z])android(?![a-z])|(?<![a-z])ios(?![a-z])|(?<![a-z])outsystems(?![a-z])|(?<![a-z])react(?![a-z])|(?<![a-z])node(?![a-z])','개발|developer|engineer|프로그래머|퍼블리셔']::text[]),
('NCS','20010303',ARRAY['(?<![a-z])it(?![a-z])|전산|desktop|컴퓨터|시스템|네트워크|technical','support|지원|help.?desk|헬프데스크']::text[]),
('NCS','23060100',ARRAY['안전관리|산업안전|industrial.?safety']::text[]),
('NCS','20010705',ARRAY['(^|[^a-z])ai([^a-z]|$)|인공지능','서비스|service','개발|구축|구현|developer|engineer|development']::text[]),
('NCS','19030804',ARRAY['로봇|robot','인지|인식|perception|vision']::text[]),
('NCS','20010209',ARRAY['빅데이터|big.?data|data.?platform|데이터.?플랫폼','구축|개발|설계|engineer|엔지니어']::text[]),
('NCS','11010101',ARRAY['물리보안|physical.?security|경비|경호']::text[]),
('NCS','19030803',ARRAY['로봇|robot','(?<![a-z])sw(?![a-z])|소프트웨어|(?<![a-z])software(?![a-z])|개발']::text[]),
('NCS','19011201',ARRAY['전장부품|전자부품|(?<![a-z])bms(?![a-z])|pack','설계|개발|design']::text[]),
('NCS','20010603',ARRAY['보안관제|security.?operations|(^|[^a-z])soc([^a-z]|$)']::text[]),
('NCS','02010302',ARRAY['customer.?success|고객관리|고객성공|(^|[^a-z])csm([^a-z]|$)']::text[]),
('NCS','20010703',ARRAY['(^|[^a-z])ml([^a-z]|$)|머신러닝|모델|model|학습','(?<![a-z])ai(?![a-z])|인공지능|engineer|엔지니어|연구|개발']::text[]),
('NCS','20010701',ARRAY['플랫폼|(?<![a-z])platform(?![a-z])|인프라|infrastructure|(?<![a-z])mlops(?![a-z])','(^|[^a-z])ai([^a-z]|$)|인공지능|머신러닝|(?<![a-z])mlops(?![a-z])']::text[]),
('NCS','20010707',ARRAY['생성형|generative|llm|프롬프트|prompt','설계|엔지니어|engineer|연구|research|개발|파이프라인']::text[]),
('NCS','08030404',ARRAY['오디오|audio|음향','engineer|엔지니어|기술|운영']::text[]),
('NCS','20010203',ARRAY['펌웨어|firmware|임베디드|embedded|(^|[^a-z])fw([^a-z]|$)']::text[]),
('NCS','20010213',ARRAY['인프라|infrastructure|서버|(?<![a-z])kubernetes(?![a-z])|(?<![a-z])k8s(?![a-z])|(?<![a-z])redis(?![a-z])','구축|설계|엔지니어|engineer']::text[]),
('NCS','19031008',ARRAY['(?<![a-z])lidar(?![a-z])|라이다','(?<![a-z])sw(?![a-z])|(?<![a-z])software(?![a-z])|소프트웨어|s/w|개발|엔지니어|engineer']::text[]),
('NCS','08030406',ARRAY['영상|이미지|video|image','편집|edit|제작']::text[]),
('NCS','19032001',ARRAY['하드웨어|h/w|(?<![a-z])hardware(?![a-z])|회로|pcb|아트웍','설계|개발|엔지니어|engineer']::text[]),
('NCS','20010706',ARRAY['데이터|(?<![a-z])data(?![a-z])|3d','라벨|label|어노테이션|annotat','자율주행|(?<![a-z])ai(?![a-z])|학습|인공지능|3d']::text[]),
('NCS','02040201',ARRAY['(?<![a-z])qc(?![a-z])|품질|quality','콜센터|고객센터|call.?center|service|서비스|품질관리|quality.?management']::text[]),
('NCS','15030102',ARRAY['(?<![a-z])plc(?![a-z])|(?<![a-z])hmi(?![a-z])','소프트웨어|(?<![a-z])software(?![a-z])|개발|설계|프로그램']::text[]),
('NCS','20010401',ARRAY['(^|[^a-z])pm([^a-z]|$)|프로젝트|project','(?<![a-z])it(?![a-z])|정보기술|소프트웨어|(?<![a-z])software(?![a-z])|mes|(?<![a-z])sap(?![a-z])|(?<![a-z])erp(?![a-z])|(?<![a-z])si(?![a-z])|클라우드|(?<![a-z])cloud(?![a-z])|시스템']::text[]),
('NCS','20010601',ARRAY['보안|security','운영|관리|monitor|관제|administrator|엔지니어|engineer']::text[]),
('NCS','20010612',ARRAY['클라우드|(?<![a-z])cloud(?![a-z])|(?<![a-z])aws(?![a-z])|(?<![a-z])azure(?![a-z])|(?<![a-z])gcp(?![a-z])','보안|security|접근통제']::text[]),
('NCS','20010602',ARRAY['모의해킹|취약점|penetration|pentest|보안점검']::text[]),
('NCS','20010207',ARRAY['(?<![a-z])ui(?![a-z])|(?<![a-z])ux(?![a-z])|사용자경험|사용자인터페이스','디자인|디자이너|design|설계|엔지니어|engineer']::text[]),
('NCS','03010501',ARRAY['결제|payment','모니터|monitor|운영|관리']::text[]),
('NCS','20010204',ARRAY['(?<![a-z])dba(?![a-z])|데이터베이스|database|(^|[^a-z])(db|dw)([^a-z]|$)','관리|설계|구축|엔지니어|engineer|개발|(?<![a-z])dba(?![a-z])']::text[]),
('NCS','20010403',ARRAY['(?<![a-z])android(?![a-z])|wearable|소프트웨어|(?<![a-z])software(?![a-z])|웹|(?<![a-z])web(?![a-z])|앱|(^|[^a-z])(it|sw)([^a-z]|$)','(?<![a-z])qa(?![a-z])|테스트|test|검증']::text[]),
('NCS','20010102',ARRAY['정보기술|정보보안|(^|[^a-z])(it|(?<![a-z])isp(?![a-z])|(?<![a-z])pi(?![a-z])|(?<![a-z])sap(?![a-z])|erp)([^a-z]|$)|클라우드|(?<![a-z])cloud(?![a-z])','컨설턴트|consultant']::text[]),
('NCS','20010306',ARRAY['데이터|(?<![a-z])data(?![a-z])','거래|trade|trading','관리|운영|management']::text[]),
('NCS','14040102',ARRAY['석유|화학|petrochemical|oil|gas','설계|design']::text[]),
('NCS','20020103',ARRAY['네트워크|(?<![a-z])network(?![a-z])','구축|설치|build|install|deployment']::text[]),
('NCS','02010303',ARRAY['통계조사|통계분석|statistical.?survey|통계.{0,8}조사']::text[]),
('NCS','19031701',ARRAY['커넥티드|connected|v2x|차량통신','(?<![a-z])sw(?![a-z])|(?<![a-z])software(?![a-z])|소프트웨어|개발']::text[]),
('NCS','20010208',ARRAY['운영체제|커널|kernel|(^|[^a-z])os([^a-z]|$)|system.?software|시스템.?sw|시스템소프트웨어|컴파일러|compiler|device.?driver|디바이스.?드라이버']::text[]),
('NCS','20010107',ARRAY['빅데이터|big.?data','기획|planning']::text[]),
('NCS','19010801',ARRAY['자동제어|automatic.?control|제어시스템','설계|design']::text[]),
('ONET','15-1252.00',ARRAY['개발|developer|프로그래머|programmer|software.?engineer|백엔드|프론트|풀스택','소프트웨어|(?<![a-z])software(?![a-z])|(?<![a-z])sw(?![a-z])|웹|앱|백엔드|프론트|풀스택|(?<![a-z])java(?![a-z])|(?<![a-z])python(?![a-z])|c\+\+|c#|\.net|(?<![a-z])ios(?![a-z])|(?<![a-z])android(?![a-z])|frontend|backend|full.stack|플랫폼|(?<![a-z])react(?![a-z])|(?<![a-z])node(?![a-z])|(?<![a-z])outsystems(?![a-z])|(?<![a-z])api(?![a-z])']::text[]),
('ONET','15-1255.00',ARRAY['(?<![a-z])ui(?![a-z])|(?<![a-z])ux(?![a-z])|웹|(?<![a-z])web(?![a-z])|인터페이스|interface','디자인|디자이너|design']::text[]),
('ONET','13-1141.00',ARRAY['compensation|benefits|보상|직무분석|급여','전문가|분석|담당|specialist|analyst|관리']::text[]),
('ONET','15-1212.00',ARRAY['보안|security','분석|운영|관제|analyst|엔지니어|engineer|정책|관리']::text[]),
('ONET','15-1253.00',ARRAY['소프트웨어|(?<![a-z])software(?![a-z])|정보기술|(^|[^a-z])(it|(?<![a-z])sw(?![a-z])|(?<![a-z])api(?![a-z])|sqa)([^a-z]|$)|웹|(?<![a-z])web(?![a-z])|앱|모바일|mobile|게임|(?<![a-z])game(?![a-z])','(?<![a-z])qa(?![a-z])|테스트|test|quality']::text[]),
('ONET','43-9061.00',ARRAY['사무|행정|office|서무|general.?affairs']::text[]),
('ONET','15-1231.00',ARRAY['네트워크|(?<![a-z])network(?![a-z])|router|라우터|서버|(?<![a-z])server(?![a-z])','지원|support|운영|유지보수|관리|엔지니어|engineer']::text[]),
('ONET','17-2141.00',ARRAY['기계|기구|mechanical|메카니컬|machine[[:space:]-]*(design|engineer|mechanic)']::text[]),
('ONET','41-4011.00',ARRAY['제품|상품|장비|설비|반도체|하드웨어|부품|equipment|(?<![a-z])hardware(?![a-z])|goods|product','영업|sales']::text[]),
('ONET','17-2072.00',ARRAY['전자|electronics|회로|circuit','설계|개발|engineer|엔지니어']::text[]),
('ONET','15-1244.00',ARRAY['시스템|system|서버|(?<![a-z])server(?![a-z])|인프라|infra|전산|네트워크|(?<![a-z])network(?![a-z])|devops|sre|(?<![a-z])it(?![a-z])','관리|운영|administrator|manager|devops|sre|유지보수']::text[]),
('ONET','13-1111.00',ARRAY['경영|프로세스|process|business|(?<![a-z])isp(?![a-z])|(^|[^a-z])pi([^a-z]|$)','컨설턴트|consultant|분석|analyst']::text[]),
('ONET','15-1299.05',ARRAY['보안|security','엔지니어|engineer|설계|개발']::text[]),
('ONET','15-1299.09',ARRAY['(^|[^a-z])(pm|pl)([^a-z]|$)|프로젝트|project','(?<![a-z])it(?![a-z])|소프트웨어|(?<![a-z])software(?![a-z])|mes|(?<![a-z])sap(?![a-z])|(?<![a-z])erp(?![a-z])|(?<![a-z])si(?![a-z])|클라우드|(?<![a-z])cloud(?![a-z])|시스템']::text[]),
('ONET','15-2051.00',ARRAY['data.?scientist|사이언티스트|데이터.?과학']::text[]),
('ONET','41-3091.00',ARRAY['영업|sales','서비스|service|컨설팅|consulting']::text[]),
('ONET','15-1232.00',ARRAY['(?<![a-z])it(?![a-z])|전산|desktop|컴퓨터|(?<![a-z])computer(?![a-z])|시스템','support|지원|help.?desk|헬프데스크']::text[]),
('ONET','15-1243.01',ARRAY['warehouse|warehousing|데이터.?웨어하우스|데이터.?웨어하우징|(^|[^a-z])dw([^a-z]|$)']::text[]),
('ONET','19-5011.00',ARRAY['안전|safety','관리|담당|전문가|산업|엔지니어|engineer']::text[]),
('ONET','17-2199.08',ARRAY['로봇|robot','개발|설계|엔지니어|engineer|(?<![a-z])sw(?![a-z])|(?<![a-z])software(?![a-z])']::text[]),
('ONET','11-3013.01',ARRAY['보안|security','매니저|manager|팀장|센터장|책임자|총괄|관리자']::text[]),
('ONET','15-1254.00',ARRAY['웹|(?<![a-z])web(?![a-z])','개발|developer|engineer|퍼블리셔']::text[]),
('ONET','17-2071.00',ARRAY['전기|electrical|전력','설계|개발|엔지니어|engineer']::text[]),
('ONET','49-9041.00',ARRAY['장비|설비|기계|equipment|machinery','정비|유지보수|보전|mechanic|maintenance']::text[]),
('ONET','15-1242.00',ARRAY['(?<![a-z])dba(?![a-z])|데이터베이스|database','관리|운영|administrator|(?<![a-z])dba(?![a-z])']::text[]),
('ONET','15-1221.00',ARRAY['연구원|연구자|research.?scientist|researcher|기초연구|알고리즘.?연구|모델.?연구']::text[]),
('ONET','17-2061.00',ARRAY['컴퓨터|(?<![a-z])computer(?![a-z])|서버|(?<![a-z])server(?![a-z])|프로세서|(?<![a-z])cpu(?![a-z])|(?<![a-z])gpu(?![a-z])|컴퓨팅|computing|메모리|memory','하드웨어|(?<![a-z])hardware(?![a-z])|(?<![a-z])hw(?![a-z])|h/w|회로|circuit']::text[]),
('ONET','49-9071.00',ARRAY['시설|건물|빌딩|facilit|building','유지보수|관리|정비|maintenance']::text[]),
('ONET','27-4011.00',ARRAY['음향|audio|영상|video|(?<![a-z])av(?![a-z])','장비|equipment|technician|기술|운영']::text[]),
('ONET','27-2022.00',ARRAY['스포츠|sport|선수|코치|coach']::text[]),
('ONET','15-1299.08',ARRAY['시스템|system','통합|integrat|엔지니어|engineer']::text[]),
('ONET','11-3021.00',ARRAY['(?<![a-z])it(?![a-z])|전산|정보|시스템|(?<![a-z])software(?![a-z])','매니저|manager|팀장|센터장|책임자|총괄|관리자']::text[]),
('ONET','15-2041.00',ARRAY['통계|statistic']::text[]),
('ONET','27-1013.00',ARRAY['아티스트|artist|그림|미술|illustrat|일러스트|컨셉.?아트']::text[]),
('ONET','15-1211.00',ARRAY['시스템|system','분석|설계|analyst']::text[]),
('ONET','11-2022.00',ARRAY['영업|sales','매니저|manager|팀장|책임자|총괄|본부장']::text[]),
('ONET','15-1241.00',ARRAY['네트워크|(?<![a-z])network(?![a-z])','아키텍|architect|설계|design']::text[]),
('ONET','43-3051.00',ARRAY['급여|payroll','사무|clerk|담당']::text[])
) contracts(scheme,code,patterns) WHERE contracts.scheme=$1 AND contracts.code=$2),false)
$$;
CREATE OR REPLACE FUNCTION replacement_matching.issues(scheme text,fields jsonb,output jsonb,match_cap integer)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE t text:=replacement_matching.field_text(fields); m jsonb; code text; why text; found jsonb:='[]';
BEGIN
 IF output->>'outcome'='abstained' THEN RETURN found; END IF;
 IF jsonb_typeof(output->'matches') IS DISTINCT FROM 'array' THEN RETURN '["POLICY_INVALID_MATCHES"]'; END IF;
 FOR m IN SELECT value FROM jsonb_array_elements(output->'matches') LOOP
  code:=m->>'occupation_code'; why:=NULL;
  IF NOT replacement_matching.supported(scheme,code,
    CASE WHEN scheme='ONET' AND code IN('11-3013.01','11-3021.00','11-2022.00','15-1241.00','15-1221.00')
    THEN lower(coalesce(fields->>'title','')) ELSE t END)
  THEN why:='SOURCE_SUPPORT_CONTRACT_NOT_SATISFIED'; END IF;
  IF scheme='NCS' AND code='20010102' THEN
   IF match_cap=1 AND t ~ '(^|[^a-z])pm[[:space:]]*/[[:space:]]*(컨설턴트|consultant)|(컨설턴트|consultant)[[:space:]]*/[[:space:]]*pm([^a-z]|$)'
   THEN why:='EXPLICIT_PM_CONSULTANT_ALTERNATIVES';
   ELSIF t ~ '비즈니스[[:space:]]*매니저|business[[:space:]]*manager|account[[:space:]]*manager|사업개발|영업'
    AND t !~ '(정보기술|it|기술|sap|erp|클라우드|cloud).{0,30}(컨설턴트|consultant)'
   THEN why:='BUSINESS_ROLE_NOT_TECHNICAL_CONSULTING'; END IF;
  ELSIF scheme='NCS' AND code='20010701' AND
   (t !~ '플랫폼|platform|인프라|infrastructure|mlops' OR t !~ '(^|[^a-z])ai([^a-z]|$)|인공지능|머신러닝|mlops')
  THEN why:='AI_PLATFORM_ROLE_NOT_EXPLICIT';
  ELSIF scheme='ONET' AND code='15-1253.00' AND t !~
   '소프트웨어|software|정보기술|(^|[^a-z])(it|sw|api|sqa)([^a-z]|$)|웹|web|앱|모바일|mobile|게임|game'
  THEN why:='SOFTWARE_QA_DOMAIN_NOT_EXPLICIT';
  ELSIF scheme='ONET' AND code='13-1141.00' AND t ~ 'hr|급여|payroll|인사'
   AND t ~ '시스템|솔루션|소프트웨어|software|erp|sap' AND t ~ '구축|개발|설계|(^|[^a-z])(pl|pm)([^a-z]|$)|project|프로젝트'
   AND t !~ '보상[[:space:]]*(전문가|담당|분석)|보상제도|보상정책|직무분석|compensation[[:space:]]*(analyst|specialist)|benefits[[:space:]]*(analyst|specialist)'
  THEN why:='HR_SOFTWARE_PROJECT_NOT_COMPENSATION_ROLE';
  ELSIF scheme='ONET' AND code='15-1231.00' AND t ~ '정보통신[[:space:]]*공사|통신[[:space:]]*공사|통신선로|광케이블|배선|구내통신'
   AND t !~ '컴퓨터|전산|라우터|router|서버|server|tcp|(^|[^a-z])(wan|lan|l2|l3)([^a-z]|$)|스위치|switch'
  THEN why:='PHYSICAL_TELECOM_COMPUTER_SCOPE_UNRESOLVED';
  ELSIF scheme='ONET' AND code='17-2141.00' AND t !~ '기계|기구|mechanical|메카니컬|machine[[:space:]-]*(design|engineer|mechanic)'
  THEN why:='MECHANICAL_SPECIALIZATION_NOT_EXPLICIT'; END IF;
  IF scheme='ONET' AND t ~ '(^|[^a-z])pm[[:space:]]*/[[:space:]]*(컨설턴트|consultant)|(컨설턴트|consultant)[[:space:]]*/[[:space:]]*pm([^a-z]|$)'
  THEN why:='ROLE_ALTERNATIVES_UNRESOLVED'; END IF;
  IF scheme='NCS' AND match_cap=1 AND
   (t ~ '(^|[^a-z])pm[[:space:]]*/[[:space:]]*(컨설턴트|consultant)|(컨설턴트|consultant)[[:space:]]*/[[:space:]]*pm([^a-z]|$)'
   OR t ~ '서비스.{0,20}개발.{0,20}/.{0,30}(기획|플래너)' OR t ~ '통계.{0,20}(총괄|분석).{0,15}(및|/).{0,20}시스템.{0,10}구축')
  THEN why:='MULTIPLE_ROLE_FUNCTIONS_UNRESOLVED'; END IF;
  IF lower(coalesce(fields->>'title','')) ~ '실시간[[:space:]]*온라인' AND t ~ '프로젝트' AND t !~ '채용|경력직|정규직|계약직|연봉|급여|강사|instructor'
  THEN why:='VACANCY_NOT_ESTABLISHED_ONLINE_PROJECT_AD'; END IF;
  IF ((scheme='ONET' AND code='15-1252.00') OR (scheme='NCS' AND code IN('20010202','20010705')))
   AND lower(coalesce(fields->>'title','')) ~ 'aspice|기능안전|functional.?safety|(^|[^a-z])pm([^a-z]|$)|프로젝트.?매니저|영업|sales|(^|[^a-z])qa([^a-z]|$)|기획'
   AND lower(coalesce(fields->>'title','')) !~ '개발자|developer|프로그래머|software.?engineer|백엔드|프론트엔드'
  THEN why:='TITLE_FUNCTION_NOT_SOFTWARE_DEVELOPER'; END IF;
  IF why IS NOT NULL THEN found:=found||jsonb_build_array('REPLACEMENT_POLICY_V1:'||code||':'||why); END IF;
 END LOOP;
 RETURN found;
END $$;
CREATE TABLE IF NOT EXISTS replacement_matching.policy (
 version text PRIMARY KEY CHECK(version='jobkorea-evidence-exclusion-v1'),
 definition_hash text NOT NULL,projector_hashes jsonb NOT NULL, assessment_kind text NOT NULL CHECK(assessment_kind='AUTOMATED_POLICY'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS replacement_matching.assessment (
 scheme text NOT NULL CHECK(scheme IN('NCS','ONET')),attempt_id text NOT NULL,
 policy_version text NOT NULL REFERENCES replacement_matching.policy,
 policy_hash text NOT NULL,source_hash text NOT NULL,output_hash text NOT NULL,
 outcome text NOT NULL CHECK(outcome IN('POLICY_ALLOWED','POLICY_BLOCKED')),
 issues jsonb NOT NULL CHECK(jsonb_typeof(issues)='array'),
 assessment_kind text NOT NULL DEFAULT 'AUTOMATED_POLICY' CHECK(assessment_kind='AUTOMATED_POLICY'),
 assessed_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(scheme,attempt_id,policy_version),
 CHECK((outcome='POLICY_ALLOWED')=(issues='[]'::jsonb))
);
CREATE OR REPLACE FUNCTION replacement_matching.immutable() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'IMMUTABLE_REPLACEMENT_POLICY_EVIDENCE'; END $$;
CREATE OR REPLACE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON replacement_matching.policy
 FOR EACH ROW EXECUTE FUNCTION replacement_matching.immutable();
CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON replacement_matching.policy
 FOR EACH STATEMENT EXECUTE FUNCTION replacement_matching.immutable();
CREATE OR REPLACE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON replacement_matching.assessment
 FOR EACH ROW EXECUTE FUNCTION replacement_matching.immutable();
CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON replacement_matching.assessment
 FOR EACH STATEMENT EXECUTE FUNCTION replacement_matching.immutable();
CREATE OR REPLACE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON replacement_matching.assessment
 FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();
CREATE OR REPLACE FUNCTION replacement_matching.definition_hash() RETURNS text LANGUAGE sql STABLE AS $$
 SELECT encode(sha256(convert_to(pg_get_functiondef('replacement_matching.field_text(jsonb)'::regprocedure)||
 pg_get_functiondef('replacement_matching.issues(text,jsonb,jsonb,integer)'::regprocedure)||pg_get_functiondef('replacement_matching.supported(text,text,text)'::regprocedure),'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION replacement_matching.resolve(scheme text,aid text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r jsonb;
BEGIN
 IF scheme='NCS' THEN
  SELECT jsonb_build_object('scoped',b.job_run_id='jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f'
   AND left(b.batch_id,17)='jkr-20261103-ncs-','fields',enrichment.metadata_occupation_fields(i.source_data),
   'source_hash',i.source_hash,'output',a.parsed_output,'state',a.state,'match_cap',(b.settings->>'max_matches')::integer)
  INTO r FROM enrichment.attempt a JOIN enrichment.item i ON i.item_id=a.item_id
  JOIN enrichment.batch b ON b.batch_id=a.batch_id WHERE a.attempt_id=aid;
 ELSIF scheme='ONET' THEN
  SELECT jsonb_build_object('scoped',t.task_id='jkr-20261103-onet'
   AND i.source_id='jobkorea' AND i.source_run_id='jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f',
   'fields',i.source_fields,'source_hash',i.input_hash,'output',a.parsed_output,'state',a.state,
   'match_cap',(t.settings->>'max_matches')::integer)
  INTO r FROM onet_matching.attempt a JOIN onet_matching.input i USING(task_id,posting_identity)
  JOIN onet_matching.task t USING(task_id) WHERE a.attempt_id=aid;
 END IF;
 RETURN r;
END $$;
CREATE OR REPLACE FUNCTION replacement_matching.assess(scheme text,aid text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r jsonb:=replacement_matching.resolve(scheme,aid); p replacement_matching.policy; problems jsonb; oh text; disposition text;
BEGIN
 PERFORM retention.gate();
 IF NOT coalesce((r->>'scoped')::boolean,false) THEN RETURN 'NOT_APPLICABLE'; END IF;
 IF r->>'state' NOT IN('VALIDATED','SKIPPED') THEN RETURN 'NOT_TECHNICALLY_VALIDATED'; END IF;
 SELECT * INTO STRICT p FROM replacement_matching.policy WHERE version='jobkorea-evidence-exclusion-v1';
 IF p.definition_hash IS DISTINCT FROM replacement_matching.definition_hash() THEN RAISE EXCEPTION 'REPLACEMENT_POLICY_DEFINITION_CHANGED'; END IF;
 problems:=replacement_matching.issues(scheme,r->'fields',r->'output',(r->>'match_cap')::integer);
 oh:=encode(sha256(convert_to((r->'output')::text,'UTF8')),'hex');
 disposition:=CASE WHEN problems='[]'::jsonb THEN 'POLICY_ALLOWED' ELSE 'POLICY_BLOCKED' END;
 INSERT INTO replacement_matching.assessment(scheme,attempt_id,policy_version,policy_hash,source_hash,output_hash,outcome,issues)
 VALUES(scheme,aid,p.version,p.definition_hash,r->>'source_hash',oh,disposition,problems) ON CONFLICT DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM replacement_matching.assessment x WHERE x.scheme=assess.scheme AND x.attempt_id=aid
  AND x.policy_version=p.version AND x.policy_hash=p.definition_hash AND x.source_hash=r->>'source_hash'
  AND x.output_hash=oh AND x.outcome=disposition AND x.issues=problems)
 THEN RAISE EXCEPTION 'REPLACEMENT_POLICY_ASSESSMENT_CONFLICT'; END IF;
 RETURN disposition;
END $$;
CREATE OR REPLACE FUNCTION replacement_matching.after_response() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF NEW.state IN('VALIDATED','SKIPPED') THEN
  PERFORM replacement_matching.assess(CASE WHEN TG_TABLE_SCHEMA='enrichment' THEN 'NCS' ELSE 'ONET' END,NEW.attempt_id);
 END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER replacement_policy_assess AFTER INSERT OR UPDATE OF state,parsed_output ON enrichment.attempt
 FOR EACH ROW EXECUTE FUNCTION replacement_matching.after_response();
CREATE OR REPLACE TRIGGER replacement_policy_assess AFTER INSERT OR UPDATE OF state,parsed_output ON onet_matching.attempt
 FOR EACH ROW EXECUTE FUNCTION replacement_matching.after_response();
CREATE OR REPLACE FUNCTION replacement_matching.triggers_ready() RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT count(*)=2 FROM pg_trigger WHERE tgname='replacement_policy_assess' AND tgenabled IN('O','A')
 AND tgrelid IN('enrichment.attempt'::regclass,'onet_matching.attempt'::regclass)
 AND tgfoid='replacement_matching.after_response()'::regprocedure
$$;
CREATE OR REPLACE FUNCTION replacement_matching.qualified_hashes() RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_object_agg(p.oid::regprocedure::text,encode(sha256(convert_to(concat_ws('|',p.prosrc,p.prorettype::text,p.proargtypes::text,p.provolatile::text,p.prosecdef::text,p.proconfig::text),'UTF8')),'hex'))
 FROM pg_proc p WHERE p.oid IN('enrichment.metadata_occupation_graph_rows(text,text,boolean)'::regprocedure,
 'onet_matching.graph_rows(text)'::regprocedure,'catalog._inferred_occupation_rows(text[],text[])'::regprocedure)
$$;
CREATE OR REPLACE FUNCTION replacement_matching.ready() RETURNS boolean LANGUAGE sql STABLE
SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM replacement_matching.policy WHERE version='jobkorea-evidence-exclusion-v1'
  AND definition_hash=replacement_matching.definition_hash() AND projector_hashes=replacement_matching.qualified_hashes()) AND replacement_matching.triggers_ready()
$$;
CREATE OR REPLACE FUNCTION replacement_matching.allowed_core(scheme text,aid text,scope_hint text DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r jsonb;
BEGIN
 IF scope_hint IS NOT NULL AND scope_hint NOT IN('jkr-20261103-onet','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f') THEN RETURN true; END IF;
 r:=replacement_matching.resolve(scheme,aid);
 IF NOT coalesce((r->>'scoped')::boolean,false) THEN
  RETURN coalesce(scope_hint NOT IN('jkr-20261103-onet','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f'),true);
 END IF;
 RETURN EXISTS(SELECT 1 FROM replacement_matching.assessment x JOIN replacement_matching.policy p ON p.version=x.policy_version
 WHERE x.scheme=allowed_core.scheme AND x.attempt_id=aid AND p.version='jobkorea-evidence-exclusion-v1'
 AND x.policy_hash=p.definition_hash AND x.source_hash=r->>'source_hash'
 AND x.output_hash=encode(sha256(convert_to((r->'output')::text,'UTF8')),'hex')
 AND x.outcome='POLICY_ALLOWED' AND x.issues='[]'::jsonb)
 AND replacement_matching.issues(scheme,r->'fields',r->'output',(r->>'match_cap')::integer)='[]'::jsonb;
END $$;
CREATE OR REPLACE FUNCTION replacement_matching.allowed(scheme text,aid text,scope_hint text DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF scope_hint IS NOT NULL AND scope_hint NOT IN('jkr-20261103-onet','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f') THEN RETURN true; END IF;
 IF NOT replacement_matching.ready() THEN RETURN false; END IF;
 RETURN replacement_matching.allowed_core(scheme,aid,scope_hint);
END $$;
CREATE OR REPLACE FUNCTION replacement_matching.backfill() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE assessed record; n integer:=0; result text;
BEGIN
 FOR assessed IN SELECT 'NCS' AS scheme,a.attempt_id FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id)
  WHERE b.job_run_id='jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f'
  AND left(b.batch_id,17)='jkr-20261103-ncs-' AND a.state IN('VALIDATED','SKIPPED')
 UNION ALL SELECT 'ONET',a.attempt_id FROM onet_matching.attempt a WHERE a.task_id='jkr-20261103-onet' AND a.state IN('VALIDATED','SKIPPED')
 LOOP result:=replacement_matching.assess(assessed.scheme,assessed.attempt_id); n:=n+1; END LOOP;
 RETURN jsonb_build_object('assessed',n,'kind','AUTOMATED_POLICY','version','jobkorea-evidence-exclusion-v1');
END $$;
CREATE OR REPLACE FUNCTION replacement_matching.require_complete(scheme text,scope_hint text) RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a record; r jsonb; missing boolean;
BEGIN
 IF scope_hint NOT IN('jkr-20261103-onet','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f') THEN RETURN; END IF;
 IF NOT replacement_matching.ready() THEN RAISE EXCEPTION 'REPLACEMENT_POLICY_NOT_READY'; END IF;
 FOR a IN SELECT x.attempt_id FROM enrichment.attempt x JOIN enrichment.batch b USING(batch_id)
  WHERE scheme='NCS' AND b.job_run_id=scope_hint AND left(b.batch_id,17)='jkr-20261103-ncs-'
  AND x.state='VALIDATED' AND x.parsed_output->>'outcome'='matched'
 UNION ALL SELECT x.attempt_id FROM onet_matching.attempt x WHERE scheme='ONET' AND x.task_id=scope_hint
  AND x.state='VALIDATED' AND x.parsed_output->>'outcome'='matched'
 LOOP
  r:=replacement_matching.resolve(scheme,a.attempt_id);
  SELECT NOT EXISTS(SELECT 1 FROM replacement_matching.assessment x JOIN replacement_matching.policy p ON p.version=x.policy_version
   WHERE x.scheme=require_complete.scheme AND x.attempt_id=a.attempt_id AND p.version='jobkorea-evidence-exclusion-v1'
   AND x.policy_hash=p.definition_hash AND x.source_hash=r->>'source_hash'
   AND x.output_hash=encode(sha256(convert_to((r->'output')::text,'UTF8')),'hex')) INTO missing;
  IF missing THEN RAISE EXCEPTION 'REPLACEMENT_POLICY_ASSESSMENT_REQUIRED'; END IF;
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION replacement_matching.publication_backstop() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF NEW.state IN('PREPARED','READY','VERIFIED') THEN
  IF TG_TABLE_SCHEMA='enrichment' THEN PERFORM replacement_matching.require_complete('NCS',NEW.job_run_id);
  ELSE PERFORM replacement_matching.require_complete('ONET',NEW.task_id); END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER replacement_policy_backstop BEFORE INSERT OR UPDATE ON enrichment.metadata_occupation_graph_guard
 FOR EACH ROW EXECUTE FUNCTION replacement_matching.publication_backstop();
CREATE OR REPLACE TRIGGER replacement_policy_backstop BEFORE INSERT OR UPDATE ON onet_matching.graph_guard
 FOR EACH ROW EXECUTE FUNCTION replacement_matching.publication_backstop();
CREATE OR REPLACE FUNCTION replacement_matching.runtime() RETURNS jsonb LANGUAGE sql STABLE
SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('ready',replacement_matching.ready(),'version',p.version,'definition_hash',p.definition_hash,
  'assessment_kind','AUTOMATED_POLICY','counts',(SELECT coalesce(jsonb_agg(to_jsonb(c)),'[]') FROM
  (SELECT scheme,outcome,count(*) n FROM replacement_matching.assessment GROUP BY scheme,outcome) c))
 FROM replacement_matching.policy p WHERE p.version='jobkorea-evidence-exclusion-v1'
$$;
'''
ncs='''CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_graph_rows(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql STABLE AS $$
 SELECT v.* FROM (
 SELECT * FROM enrichment.metadata_occupation_graph_rows_legacy(jobs,ncs,include_unreviewed)
 UNION ALL SELECT * FROM enrichment.metadata_occupation_graph_rows_v3(jobs,ncs,include_unreviewed)) v
 WHERE jobs<>'jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f'
 OR ((SELECT replacement_matching.ready()) AND replacement_matching.allowed_core('NCS',v.payload->>'attempt_id',jobs))
$$;
'''
onet=re.search(r'CREATE OR REPLACE FUNCTION onet_matching.graph_rows\(.*?\$\$;', (ROOT/'hop/llm/onet/sql/003_publication.sql').read_text(),re.S).group()
onet=onet.replace("WHERE t.task_id=id AND a.state='VALIDATED'", "WHERE t.task_id=id AND (t.task_id<>'jkr-20261103-onet' OR ((SELECT replacement_matching.ready()) AND replacement_matching.allowed_core('ONET',a.attempt_id,t.task_id))) AND a.state='VALIDATED'")
reader=re.search(r'CREATE OR REPLACE FUNCTION catalog\._inferred_occupation_rows\(.*?END \$\$;', (ROOT/'hop/ontology/sql/037_jobkorea_replacement.sql').read_text(),re.S).group()
reader=reader.replace("WHERE s.output->>'outcome'='matched' AND", "WHERE (s.job_run_id<>'jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f' OR ((SELECT replacement_matching.ready()) AND replacement_matching.allowed('NCS',s.attempt_id,s.job_run_id))) AND s.output->>'outcome'='matched' AND")
reader=reader.replace("WHERE g.state='VERIFIED' AND EXISTS", "WHERE g.state='VERIFIED' AND (g.task_id<>'jkr-20261103-onet' OR ((SELECT replacement_matching.ready()) AND replacement_matching.allowed('ONET',coalesce(e.properties->>'attempt_id',e.payload_json::jsonb->>'attempt_id'),g.task_id))) AND EXISTS")
registration="INSERT INTO replacement_matching.policy(version,definition_hash,projector_hashes,assessment_kind)\n VALUES('jobkorea-evidence-exclusion-v1',replacement_matching.definition_hash(),replacement_matching.qualified_hashes(),'AUTOMATED_POLICY') ON CONFLICT DO NOTHING;\nDO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM replacement_matching.policy WHERE version='jobkorea-evidence-exclusion-v1'\n AND definition_hash=replacement_matching.definition_hash() AND projector_hashes=replacement_matching.qualified_hashes()) THEN RAISE EXCEPTION 'IMMUTABLE_REPLACEMENT_POLICY_VERSION_COLLISION'; END IF; END $$;\n"
end='''REVOKE ALL ON SCHEMA replacement_matching FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA replacement_matching FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA replacement_matching FROM PUBLIC;
COMMIT;
'''
helpers=re.search(r'-- Optional policy hooks.*?REVOKE ALL ON FUNCTION catalog\._replacement_policy_ready\(\),catalog\._replacement_policy_allowed\(text,text,text\) FROM PUBLIC;', (ROOT/'hop/ontology/sql/037_jobkorea_replacement.sql').read_text(),re.S).group()
bridges='\n'.join(re.search(r'CREATE OR REPLACE FUNCTION ingestion\.'+name+r'\(.*?\$\$;', (ROOT/'hop/ontology/sql/037_jobkorea_replacement.sql').read_text(),re.S).group() for name in ('jobkorea_ncs_publication_allowed','jobkorea_onet_publication_allowed'))
body=core+ncs+onet+'\n'+helpers+bridges+reader+'\n'+registration+end
body=body.removeprefix('-- New-cohort automated exclusion only. Technical responses/review/accounting stay exact.\nBEGIN;\nSELECT retention.gate();\n').removesuffix('COMMIT;\n')
optional="BEGIN;\nDO $optional_policy$ BEGIN\n IF to_regclass('enrichment.attempt') IS NULL OR to_regclass('onet_matching.attempt') IS NULL OR to_regprocedure('catalog._inferred_occupation_rows(text[],text[])') IS NULL THEN RETURN; END IF;\n PERFORM retention.gate();\n EXECUTE $policy_ddl$\n"+body+"\n$policy_ddl$; END $optional_policy$;\nCOMMIT;\n"
(ROOT/'hop/llm/sql/038_replacement_policy.sql').write_text(optional)

# Real source fields → Hop normalized fields

Use these with [the real-data guide](../hop-real-data-guide.md). They mirror
[`processing/sources.py`](../../src/jobtology_db/processing/sources.py) and
[`contracts/processing.py`](../../src/jobtology_db/contracts/processing.py), inspected 2026-09-10.
Field names on the right are the **JSON Output element names**, then PostgreSQL normalized keys.
These mappings cover all six implemented source record types.

## Common conversion rules

First preserve the complete source object as `source_payload_json`. Read individual fields from
that object with a second JSON Input, using `$.<provider_field>`; CSV uses its column names.

- Read codes/identifiers as **String**, including numeric-looking ones. Keep leading zeroes and
  full NCS version suffixes. Reject object/array/boolean values where a scalar is expected.
- For mapped text: normalize CRLF/CR to LF, Unicode to NFC, and trim surrounding whitespace.
  Empty/whitespace-only optional values become SQL/JSON null. Required text must remain nonempty.
  Keep the untrimmed original in `source_payload_json` and its raw response file.
- Native choices: **String Operations**, **Replace in String**, **Null If**, **Select Values**,
  **Regex Evaluation**, **Data Validator**, **Filter Rows**. NFC can be done in parameterized
  **Database Join**, e.g. `SELECT normalize(CAST(? AS text), NFC) AS normalized_text` on UTF8
  PostgreSQL, binding the original field and appending the result to the row. See
  [PostgreSQL text normalization](https://www.postgresql.org/docs/17/functions-string.html).
- Integers: validate `^[0-9]+$` before conversion; optional empty values stay null. Reject
  fractional, negative, boolean, or malformed values. Do not replace missing hours/headcount by 0.
- Dates: require exactly eight digits, strictly parse `yyyyMMdd`, and round-trip to that format
  to reject rollover such as February 30. Convert valid values to **String `yyyy-MM-dd`** for
  JSON Output. Null stays null. Never manufacture a time of day or timezone.
- JSON Output must preserve numeric/boolean types, nullable keys and proper string escaping.
  Use block `row`, one row per block, compatibility mode off. The supplied loader unwraps it.
- Add `kind` as a constant. Add all listed optional output keys even when their values are null.
  Field validators run before the loader; the database manifest checks do not replace them.
- Keep field lineage such as `{"name":["/instNm"]}`. Paths are relative to the preserved
  source object; JSON-pointer escaping is `~` → `~0`, `/` → `~1`. Combine with the document
  locator to find the original source value. Request-derived fields use `request:partition_id`.

## ALIO organizations

Set `kind = Organization`. Item objects: `$.result[*]` in a page.

| Provider field | Output key | Type / rule |
|---|---|---|
| `instCd` | `code` | Required String; identity |
| `instNm` | `name` | Required String |
| `pbadmsStdInstCd` | `government_code` | Nullable String |
| `instTypeNm` | `organization_type` | Nullable String |
| `sprvsnInstCd` | `supervising_organization_code` | Nullable String |
| `siteUrl` | `website` | Nullable String |
| `roadNmAddr` | `address` | Nullable String |
| `fndnYmd` | `established_date` | Nullable date |

The public organization code is the employer join key for JOB-ALIO. Do not join organizations
by a cleaned name. Target view: `ingestion.organization`.

## JOB-ALIO postings

Set `kind = JobPosting`. List item: `$.result[*]`; detail object: `$.result`.

| Provider field / context | Output key | Type / rule |
|---|---|---|
| `recrutPblntSn` | `posting_id` | Required String |
| `index` / `detail-<id>` partition | `representation` | Literal `list` / `detail` |
| `recrutPbancTtl` | `title` | Required String |
| `pblntInstCd` | `organization_code` | Required String |
| `instNm` | `organization_name` | Required String |
| `pbancBgngYmd` | `date_posted` | Required date |
| `pbancEndYmd` | `closing_date` | Required date; must be ≥ posted date |
| `ongoingYn` | `ongoing` | `Y` → Boolean true; `N` → false; absent/empty → null; reject other values |
| `srcUrl` | `source_url` | Nullable String |
| `recrutSeNm` | `recruitment_type` | Nullable String |
| `acbgCondNmLst` | `education` | Nullable String |
| `hireTypeNmLst` | `employment_type` | Nullable String |
| `workRgnNmLst` | `regions` | Nullable String |
| `ncsCdLst` | `ncs_category_codes` | Nullable String; retain source's list representation |
| `ncsCdNmLst` | `ncs_category_names` | Nullable String |
| `recrutNope` | `headcount` | Nullable nonnegative Integer |
| `aplyQlfcCn` | `eligibility_text` | Nullable String; preserve full text |
| `disqlfcRsn` | `disqualification_text` | Nullable String |
| `prefCn` | `preference_text` | Nullable String |
| `scrnprcdrMthdExpln` | `selection_text` | Nullable String |

For detail, the returned posting ID must equal the requested `sn`. Both representations must
exist within the same run. Title, organization code and the two dates must agree. If detail
supplies a non-null `ongoing`, it must equal the list value. A null detail value can inherit list.
The current check does not require identical employer display names; retain each source value.

The loader generates IDs `<posting_id>:list` and `<posting_id>:detail`. Keep both rows in
`record`; `posting_representation` exposes them. `job_posting` assembles one draft per pair with
detail-over-list null fallback and retains both document locations and field origins.

## NCS competency API

Set `kind = Competency`. Items: `$.root.items[*]`.

| Provider field | Output key | Type / rule |
|---|---|---|
| `ncsClCd` | `code` | Required String matching `^[0-9]{10}_[0-9]{2}v[0-9]+$` |
| `compeUnitName` | `name` | Required String |
| `compeUnitDef` | `definition` | Nullable String |
| `compeUnitLevel` | `level` | Integer 1–8; 0 → null and flag below; other values rejected |
| First eight characters of `ncsClCd` | `occupation_code` | String; lineage `/ncsClCd` |
| `ncsSubdCdnm` | `occupation_name` | Required String |
| `ncsLclasCdnm` | `classification_1` | Source String, missing → empty String |
| `ncsMclasCdnm` | `classification_2` | Source String, missing → empty String |
| `ncsSclasCdnm` | `classification_3` | Source String, missing → empty String |

The three classification fields retain their source strings in order, as in the current parser.
`load-record.sql` turns them into `classification_names: [large, middle, small]` and removes the
temporary fields. Its lineage lists the three corresponding source pointers in that order.
For level 0 set `quality_flags_json` to `["UNSPECIFIED_COMPETENCY_LEVEL"]`; otherwise use `[]`.
Store the full API dataset. The 11-name allowlist filters only the **next API's requests**.

Identity is the full versioned code, e.g. `1501020207_14v2`, not its ten-digit prefix.
Target view: `ingestion.competency`.

## NCS qualification mappings

Set `kind = QualificationMapping`. Items: `$.body.items[*]`.

| Provider field | Output key | Type / rule |
|---|---|---|
| `ncsClCd` | `competency_code` | Full versioned String, must match request `ncsClCd` |
| `jmCd` | `qualification_code` | Required String; four alphanumeric characters for Q-Net partition derivation |
| `jmNm` | `qualification_name` | Required String |
| `organStdVerCd` | `standard_version` | Required String |
| `abltUnitTypCd` | `unit_type` | Required String |
| `minEduTrngTm` | `minimum_training_hours` | Nullable nonnegative Integer |
| `eduTrngStdTmSum` | `total_training_hours` | Nullable nonnegative Integer |
| `examInstiNm` | `examining_organization` | Nullable String |

Identity is `competency_code:qualification_code:standard_version`. Omitting the standard version
loses real rows: the recorded 87 mappings contain only 85 distinct NCS/qualification pairs.
Keep `unit_type` and training-hour qualifiers; a mapping alone is not an accepted skill claim.
Target view: `ingestion.qualification_mapping`.

## Q-Net examination schedules

Set `kind = ExamSession`. Items: `$.body.items[*]`.

| Provider field / context | Output key | Type / rule |
|---|---|---|
| Requested `jmCd` | `qualification_code` | Required String; do not rely on presence in response |
| `implYy` | `year` | Integer 1900–2200; must equal requested year |
| `implSeq` | `round` | Integer ≥ 1 |
| `qualgbCd` | `category_code` | Required String |
| `description` | `name` | Required String |

If a response does supply `jmCd`, require it to match the request. Identity includes all four of
`qualification_code:year:category_code:round`. Qualification lineage is `request:partition_id`.

Read these ten fields as nullable dates. Use these exact names as flat JSON Output elements;
`load-record.sql` moves them into a single `dates` object with all ten keys:

| Provider / flat output key | Meaning |
|---|---|
| `docRegStartDt`, `docRegEndDt` | Written-exam registration start/end |
| `docExamStartDt`, `docExamEndDt` | Written-exam dates |
| `docPassDt` | Written result date |
| `pracRegStartDt`, `pracRegEndDt` | Practical-exam registration start/end |
| `pracExamStartDt`, `pracExamEndDt` | Practical-exam dates |
| `pracPassDt` | Practical result date |

Reject a start later than its corresponding end when both exist. A missing result/application
date stays null. Example lineage: `"dates.docRegStartDt": ["/docRegStartDt"]`.
Target view: `ingestion.exam_session`.

## NCS career-path CSV

Set `kind = CareerPath`. Read the header row and quoted CSV records. The inspected saved file is
**CP949**; the reference parser also accepts UTF-8 with BOM. Select the actual file's encoding.
Keep the complete CSV row as a JSON object keyed by the original Korean column names.

| Provider column / calculation | Output key | Type / rule |
|---|---|---|
| `대분류코드` + `중분류코드` + `소분류코드` + `직무코드` | `occupation_code` | Validate each as integer 0–99; pad each to two digits, then concatenate to eight digits |
| `직무명` | `occupation_name` | Required String |
| `occupation_code` + padded `직무역량코드` | `competency_code` | Validate unit part 0–99; ten-digit **unversioned** String |
| `직무역량명` | `competency_name` | Required String |
| `직무역량수준(능력단위수준 이면서 세분류의 자식)` | `competency_level` | Integer 1–8 |
| `수준(직급수준)` | `rank_level` | Integer 1–8 |
| `직급명` | `rank_name` | Required String |

Use String Operations padding and Concat Fields, or bound SQL `lpad(code, 2, '0')` **after**
checking the range; `lpad` can truncate an oversized input. Occupation lineage lists the four
code columns; competency lineage adds `/직무역량코드`.

`load-record.sql` makes a migration-specific hash of the full normalized row. It deliberately
does not reuse Python's serialization-dependent CareerPath ID. Compare the normalized facts.
Never merge the unversioned unit into a versioned API unit just because prefixes match.
Target view: `ingestion.career_path`.

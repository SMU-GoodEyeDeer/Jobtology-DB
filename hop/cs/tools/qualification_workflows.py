"""Generate read-only Hop qualification coverage workflows and SQL installer."""

import xml.etree.ElementTree as E


detail_params = [
    ('POSTING_IDENTITY', '', 'Required exact source-qualified posting identity; blank returns no rows.'),
    ('TECHNICAL_ONLY', 'Y', 'Y shows category-20 NCS links; N includes other accepted NCS categories.'),
    ('ROW_LIMIT', '1000', 'Maximum detail rows to preview.'),
]
p = Pipe('read_qualification',
         'Read current accepted in-scope role links and best-effort NCS credentials; no provider calls.')
p.chain(
    variables('Qualification selection', [
        ('posting_identity', '${POSTING_IDENTITY}', 'String'),
        ('technical_only', '${TECHNICAL_ONLY}', 'String'),
        ('row_limit', '${ROW_LIMIT}', 'String'),
    ]),
    db('Current role qualification status',
       "SELECT source_id,source_posting_id,posting_identity,role_id,role_name,"
       "binding_hash,selected_family,candidate_id,ncs_unit_code,ncs_unit_name,"
       "occupation_code,occupation_name,ncs_category,qualification_code,"
       "qualification_name,qualification_status,exam_status,"
       "jsonb_array_length(exam_sessions) AS exam_session_count,"
       "qualification_run_id,qnet_run_id "
       "FROM cs.current_role_qualification "
       "WHERE posting_identity=?::text "
       "AND (?::text='N' OR ncs_category='TECHNICAL_CATEGORY_20') "
       "ORDER BY source_id,posting_identity,role_id,ncs_unit_code,qualification_code "
       "LIMIT ?::integer",
       [('posting_identity', 'String'), ('technical_only', 'String'),
        ('row_limit', 'String')]),
    node('Dummy', 'Preview qualification rows'),
)
p.save()
workflow('read_qualification.hwf', 'Read accepted CS role qualification status',
         detail_params, [('Read qualification detail', 'read_qualification.hpl')], False)

summary_params = [
    ('POSTING_IDENTITY', '', 'Required exact source-qualified posting identity; blank returns no rows.'),
    ('ROW_LIMIT', '1000', 'Maximum in-scope roles to preview.'),
]
p = Pipe('read_qualification_summary',
         'Summarize related credentials and explicit qualification/exam gaps per in-scope role.')
p.chain(
    variables('Summary selection', [
        ('posting_identity', '${POSTING_IDENTITY}', 'String'),
        ('row_limit', '${ROW_LIMIT}', 'String'),
    ]),
    db('Current role qualification summary',
       "SELECT source_id,source_posting_id,posting_identity,role_id,role_name,"
       "binding_hash,selected_family,accepted_ncs_links,technical_ncs_links,"
       "other_ncs_links,related_credentials,unfetched_links,"
       "fetched_without_mapping_links,no_ready_qualification_links,"
       "credentials_with_exam_sessions,credentials_without_current_exam_sessions,"
       "qualification_run_id,qnet_run_id "
       "FROM cs.current_role_qualification_summary "
       "WHERE posting_identity=?::text "
       "ORDER BY source_id,posting_identity,role_id LIMIT ?::integer",
       [('posting_identity', 'String'), ('row_limit', 'String')]),
    node('Dummy', 'Preview role coverage'),
)
p.save()
workflow('read_qualification_summary.hwf', 'Summarize CS role qualification coverage',
         summary_params, [('Read qualification summary', 'read_qualification_summary.hpl')], False)

w = E.Element('workflow')
put(w, 'name', 'Install CS qualification status views')
put(w, 'description', 'Install read-only, source-qualified accepted-role qualification views')
put(w, 'workflow_version', '1')
put(w, 'workflow_status', '0')
E.SubElement(w, 'parameters')
actions = E.SubElement(w, 'actions')
hops = E.SubElement(w, 'hops')
child(actions, 'action', dict(name='Start', type='SPECIAL', start='Y', repeat='N',
                              xloc=80, yloc=80, draw='Y', parallel='N'))
child(actions, 'action', dict(name='Install 007 qualification status SQL', type='SQL',
                              connection='jobtology-postgres', sqlfromfile='Y',
                              sqlfilename='${PROJECT_HOME}/cs/sql/007_qualification_status.sql',
                              sqlfilename_encoding='UTF-8', useVariableSubstitution='N',
                              sendOneStatement='Y', xloc=320, yloc=80,
                              draw='Y', parallel='N'))
child(actions, 'action', dict(name='Success', type='SUCCESS', xloc=560, yloc=80,
                              draw='Y', parallel='N'))
child(actions, 'action', dict(name='Abort', type='ABORT',
                              message='CS qualification status SQL installation failed.',
                              xloc=560, yloc=240, draw='Y', parallel='N'))
for source, target, success in [
    ('Start', 'Install 007 qualification status SQL', True),
    ('Install 007 qualification status SQL', 'Success', True),
    ('Install 007 qualification status SQL', 'Abort', False),
]:
    child(hops, 'hop', {'from': source, 'to': target, 'enabled': 'Y',
                       'evaluation': 'Y' if success else 'N',
                       'unconditional': 'Y' if source == 'Start' else 'N'})
E.SubElement(w, 'notepads')
E.SubElement(w, 'attributes')
save(w, OUT / 'install_qualification_status.hwf')

"""Fast adapter checks; real-format regressions also run through the Docker image."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import server
from worker import project, project_archive


class Dump:
    def __init__(self, value):
        self.value = value

    def model_dump(self, **_):
        return self.value.copy()


class Document(Dump):
    def to_semantic(self):
        return Dump({'blocks': [{'text': '업무\x00관리', 'node_id': 'paragraph:1',
                                 'kind': 'paragraph'}]})


class ContractTests(unittest.TestCase):
    def test_nul_normalization_keeps_original_input_and_auditable_offsets(self):
        doc = Document({'paragraphs': [{'text': '업무\x00관리'}]})
        result = project(doc)
        self.assertEqual(result['markdown'], '업무\ufffd관리')
        self.assertEqual(doc.value['paragraphs'][0]['text'], '업무\x00관리')
        self.assertIn('NUL_REPLACED_WITH_U_FFFD', result['warnings'])
        self.assertEqual(result['sections'][0]['content_hash'], hashlib.sha256(result['markdown'].encode()).hexdigest())
        self.assertNotIn('\\u0000', json.dumps(result))
        self.assertEqual({x['path'] for x in result['normalization']['nul_replacements']},
                         {'semantic.blocks[0].text', 'structure.paragraphs[0].text'})

    def test_integrity_and_archive_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'source.pdf'
            path.write_bytes(b'%PDF-fixture')
            request = dict(path=str(path), extension='pdf', raw_hash=hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(server.validate(request, root), path)
            with self.assertRaisesRegex(ValueError, 'SOURCE_HASH_MISMATCH'):
                server.validate(request | {'raw_hash': '0'*64}, root)
            with self.assertRaisesRegex(ValueError, 'PATH_OUTSIDE_DOCUMENT_ROOT'):
                server.validate(request, root/'different-mount')
            archive = root/'unsafe.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('../outside.hwp', b'not extracted')
            with self.assertRaisesRegex(ValueError, 'UNSAFE_ARCHIVE_MEMBER'):
                server.validate(dict(path=str(archive), extension='zip',
                    raw_hash=hashlib.sha256(archive.read_bytes()).hexdigest()), root)

    def test_nested_zip_preserves_both_member_hashes_and_block_offsets(self):
        leaf = b'%PDF-source-bound-inner-fixture'
        direct = b'%PDF-direct-fixture'
        nested = BytesIO()
        with zipfile.ZipFile(nested, 'w') as output:
            output.writestr('신입직/5. 정보보안.pdf', leaf)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'source.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('신입직.zip', nested.getvalue())
                output.writestr('direct.pdf', direct)
            server.validate(dict(path=str(archive), extension='zip',
                raw_hash=hashlib.sha256(archive.read_bytes()).hexdigest()), root)
            with patch('worker.parse_document', return_value=project(Document({'paragraphs': []}))) as parse:
                result = project_archive(archive, object())
            self.assertEqual(parse.call_count, 2)
        self.assertEqual(result['state'], 'PARSED')
        self.assertEqual(result['warnings'], ['NUL_REPLACED_WITH_U_FFFD'])
        container, inner, direct_member = result['structure']['members']
        self.assertEqual(container['state'], 'CONTAINER')
        self.assertEqual(container['raw_hash'], hashlib.sha256(nested.getvalue()).hexdigest())
        self.assertEqual(container['member_count'], 1)
        self.assertEqual(inner['name'], '신입직.zip!/신입직/5. 정보보안.pdf')
        self.assertEqual(inner['raw_hash'], hashlib.sha256(leaf).hexdigest())
        self.assertEqual([(x['name'], x['ordinal'], x['raw_hash']) for x in inner['archive_chain']],
            [('신입직.zip', 1, container['raw_hash']),
             ('신입직/5. 정보보안.pdf', 1, inner['raw_hash'])])
        self.assertEqual(direct_member['name'], 'direct.pdf')
        self.assertEqual(direct_member['raw_hash'], hashlib.sha256(direct).hexdigest())
        self.assertIn('## 신입직.zip!/신입직/5. 정보보안.pdf\n\n업무\ufffd관리', result['markdown'])
        self.assertEqual(result['text_hash'], hashlib.sha256(result['markdown'].encode()).hexdigest())
        for index, section in enumerate(result['sections']):
            if index:
                self.assertEqual(section['start'], result['sections'][index-1]['end']+2)
            text = result['markdown'][section['start']:section['end']]
            self.assertEqual(section['content_hash'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(result['sections'][-1]['end'], len(result['markdown']))
        self.assertEqual(result['sections'][0]['locator'], '1:1')
        self.assertEqual(result['sections'][1]['member_raw_hash'], inner['raw_hash'])
        self.assertEqual(result['sections'][2]['locator'], '2')

    def test_unsafe_nested_zip_is_rejected_before_parsing_any_leaf(self):
        nested = BytesIO()
        with zipfile.ZipFile(nested, 'w') as output:
            output.writestr('../escape.pdf', b'%PDF-unsafe')
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'outer.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('inner.zip', nested.getvalue())
            with patch('worker.parse_document') as parse:
                result = project_archive(archive, object())
            parse.assert_not_called()
        self.assertEqual(result['state'], 'NO_TEXT')
        self.assertEqual(result['structure']['members'][0]['state'], 'PARSE_ERROR')
        self.assertEqual(result['structure']['members'][0]['issue'], 'UNSAFE_ARCHIVE_MEMBER')
        self.assertIn('UNPARSED_ARCHIVE_MEMBER', result['warnings'])

    def test_nested_zip_depth_and_total_member_count_are_bounded(self):
        deep = BytesIO()
        with zipfile.ZipFile(deep, 'w') as output:
            output.writestr('role.pdf', b'%PDF-deep')
        nested = BytesIO()
        with zipfile.ZipFile(nested, 'w') as output:
            output.writestr('third.zip', deep.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'outer.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('inner.zip', nested.getvalue())
            with patch('worker.parse_document') as parse:
                result = project_archive(archive, object())
            parse.assert_not_called()
            self.assertEqual(result['structure']['members'][1]['state'], 'UNSUPPORTED_FORMAT')
            self.assertIn('UNSUPPORTED_ARCHIVE_MEMBER', result['warnings'])
            nested = BytesIO()
            with zipfile.ZipFile(nested, 'w') as output:
                for i in range(100):
                    output.writestr(f'{i}.pdf', b'%PDF-fixture')
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('inner.zip', nested.getvalue())
            with patch('worker.parse_document') as parse:
                with self.assertRaisesRegex(ValueError, 'ARCHIVE_MEMBER_COUNT_LIMIT'):
                    project_archive(archive, object())
            parse.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Fast adapter checks; real-format regressions also run through the Docker image."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import server
from worker import project


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


if __name__ == '__main__':
    unittest.main()

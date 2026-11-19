from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shared/python'))
from credential_store import resolve


class CredentialTests(unittest.TestCase):
    def test_wiki_ref_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory)
            (store / 'cube-token.json').write_text('{"value":"example"}', encoding='utf-8')
            with patch('credential_store.STORE', store):
                self.assertEqual(resolve({'token_ref': 'cube-token'}, 'token'), 'example')
                with self.assertRaisesRegex(ValueError, 'unavailable'):
                    resolve({'token_ref': 'missing'}, 'token')
                with self.assertRaisesRegex(ValueError, 'Invalid'):
                    resolve({'token_ref': '../outside'}, 'token')

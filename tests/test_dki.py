import unittest

from digibib.dki import decode


class AuthorSignatureTest(unittest.TestCase):
    def test_page_change_inside_signature(self):
        # Aiakos has a print-page change before the signature's closing token.
        body = b"\x01\x05Ende.\x04\x00\x0e\x01\x02Be\x0f\x14\x00\x05\x03"
        page = decode(body, modern=True, author_signatures={"Be"})
        self.assertEqual(page.text, "Ende.\n\n— Be")
        self.assertEqual(page.prose, "Ende.\n\n— Be")
        self.assertEqual(page.numbers, (20,))

    def test_unrecognized_word_remains_in_the_paragraph(self):
        body = b"\x01\x05Ende.\x04\x00\x0e\x01\x02Be\x0f\x14\x00\x05\x03"
        page = decode(body, modern=True, author_signatures={"Jo"})
        self.assertEqual(page.text, "Ende. Be")
        self.assertEqual(page.numbers, (20,))

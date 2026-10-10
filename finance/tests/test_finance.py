from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from finance.validators import validate_receipt


class ReceiptValidatorTests(TestCase):
    def test_accepts_real_pdf_png_jpg(self):
        validate_receipt(SimpleUploadedFile("r.pdf", b"%PDF-1.4 data"))
        validate_receipt(SimpleUploadedFile("r.png", b"\x89PNG\r\n\x1a\n...."))
        validate_receipt(SimpleUploadedFile("r.JPG", b"\xff\xd8\xff\xe0...."))

    def test_rejects_wrong_extension(self):
        with self.assertRaises(ValidationError):
            validate_receipt(SimpleUploadedFile("evil.exe", b"MZ..."))
        with self.assertRaises(ValidationError):
            validate_receipt(SimpleUploadedFile("page.html", b"<script>"))

    def test_rejects_fake_extension(self):
        with self.assertRaises(ValidationError):
            validate_receipt(SimpleUploadedFile("fake.pdf", b"<script>alert(1)</script>"))

    def test_rejects_big_files(self):
        with self.assertRaises(ValidationError):
            validate_receipt(SimpleUploadedFile("big.pdf", b"%PDF" + b"0" * (2 * 1024 * 1024 + 1)))

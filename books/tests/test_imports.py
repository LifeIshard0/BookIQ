"""Importer tests for stream handling, malformed uploads, and duplicate rows."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from books.management.commands.import_books import Command
from books.views import ImportJobViewSet
from books.services.importer import _open_csv_text_stream, process_csv_import


class FakeField:
	# Tiny stand-in that exposes the max_length attribute the importer expects.
	def __init__(self, max_length=None):
		self.max_length = max_length


class FakeBookManager:
	def __init__(self, duplicate_candidates=None):
		self.duplicate_candidates = duplicate_candidates or []
		self.bulk_create = MagicMock()

	def exclude(self, *args, **kwargs):
		return self

	def values_list(self, *args, **kwargs):
		return []

	def only(self, *args, **kwargs):
		return self.duplicate_candidates


class FakeBookFactory:
	# Mimics the bits of Django's Book model that the importer touches.
	def __init__(self, manager):
		self.objects = manager
		self._meta = SimpleNamespace(
			get_field=lambda name: FakeField(
				{
					'title': 500,
					'author': 300,
					'isbn_13': 13,
					'description': None,
					'genre': 100,
					'publisher': 300,
					'language': 10,
					'cover_url': None,
					'normalized_title': 500,
					'normalized_author': 300,
				}.get(name)
			)
		)

	def __call__(self, **kwargs):
		return SimpleNamespace(**kwargs)


class ImportTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.admin = SimpleNamespace(username='admin', role='admin', is_authenticated=True)

	def test_open_csv_text_stream_reads_from_path(self):
		with NamedTemporaryFile('w', encoding='utf-8', newline='', suffix='.csv', delete=False) as temp_file:
			temp_file.write('title,authors\nTest Book,Test Author\n')
			temp_path = Path(temp_file.name)

		try:
			with _open_csv_text_stream(temp_path) as stream:
				self.assertEqual(stream.readline(), 'title,authors\n')
		finally:
			temp_path.unlink(missing_ok=True)

	# Valid CSV rows should update the job counters and call bulk_create once.
	def test_process_csv_import_streams_rows_and_updates_job(self):
		with NamedTemporaryFile('w', encoding='utf-8', newline='', suffix='.csv', delete=False) as temp_file:
			temp_file.write(
				'title,authors,isbn13,description,categories,published_year,num_pages,publisher,language\n'
				'Book One,Author One,9780306406157,First book,Fantasy,2001,101,Publisher,en\n'
				'Book Two,Author Two,9780306406158,Second book,Fantasy,2002,102,Publisher,en\n'
			)
			temp_path = Path(temp_file.name)

		fake_job = SimpleNamespace(
			status='pending',
			file_name='',
			total_rows=0,
			cleaned_count=0,
			duplicate_count=0,
			failed_count=0,
			error_log=[],
			completed_at=None,
			save=MagicMock(),
		)
		fake_statuses = SimpleNamespace(
			PENDING='pending',
			PROCESSING='processing',
			COMPLETED='completed',
			FAILED='failed',
		)
		fake_import_job_model = SimpleNamespace(Status=fake_statuses)
		fake_manager = FakeBookManager()
		fake_book_factory = FakeBookFactory(fake_manager)
		fake_user = SimpleNamespace(username='admin')

		try:
			with patch('books.services.importer.Book', fake_book_factory), \
				 patch('books.services.importer.ImportJob', fake_import_job_model), \
				 patch('books.services.importer.run_cleaning_pipeline') as mock_pipeline, \
				 patch('books.services.importer.timezone.now', return_value='now'):
				mock_pipeline.side_effect = lambda data, **kwargs: {
					**data,
					'genre': data.get('genre', 'Fantasy'),
					'normalized_title': data['title'],
					'normalized_author': data['author'],
					'genre_confidence': 1.0,
					'quality_score': 1.0,
					'is_flagged': False,
				}

				result = process_csv_import(temp_path, 'sample.csv', fake_user, fake_job)

			self.assertIs(result, fake_job)
			self.assertEqual(fake_job.total_rows, 2)
			self.assertEqual(fake_job.cleaned_count, 2)
			self.assertEqual(fake_job.duplicate_count, 0)
			self.assertEqual(fake_job.failed_count, 0)
			self.assertEqual(fake_job.status, 'completed')
			self.assertEqual(fake_manager.bulk_create.call_count, 1)
			self.assertEqual(mock_pipeline.call_count, 2)
			self.assertIn('duplicate_candidates', mock_pipeline.call_args_list[0].kwargs)
			self.assertEqual(mock_pipeline.call_args_list[0].kwargs['duplicate_candidates'], [])
		finally:
			temp_path.unlink(missing_ok=True)

	# A repeated ISBN in the same file should be counted as a duplicate.
	def test_process_csv_import_counts_duplicate_rows(self):
		with NamedTemporaryFile('w', encoding='utf-8', newline='', suffix='.csv', delete=False) as temp_file:
			temp_file.write(
				'title,authors,isbn13,description,categories,published_year,num_pages,publisher,language\n'
				'Duplicate One,Author One,9780306406157,First book,Fantasy,2001,101,Publisher,en\n'
				'Duplicate Two,Author Two,9780306406157,Second book,Fantasy,2002,102,Publisher,en\n'
			)
			temp_path = Path(temp_file.name)

		fake_job = SimpleNamespace(
			status='pending',
			file_name='',
			total_rows=0,
			cleaned_count=0,
			duplicate_count=0,
			failed_count=0,
			error_log=[],
			completed_at=None,
			save=MagicMock(),
		)
		fake_statuses = SimpleNamespace(
			PENDING='pending',
			PROCESSING='processing',
			COMPLETED='completed',
			FAILED='failed',
		)
		fake_import_job_model = SimpleNamespace(Status=fake_statuses)
		fake_manager = FakeBookManager()
		fake_book_factory = FakeBookFactory(fake_manager)
		fake_user = SimpleNamespace(username='admin')

		try:
			with patch('books.services.importer.Book', fake_book_factory), \
				 patch('books.services.importer.ImportJob', fake_import_job_model), \
				 patch('books.services.importer.run_cleaning_pipeline') as mock_pipeline, \
				 patch('books.services.importer.timezone.now', return_value='now'):
				mock_pipeline.side_effect = lambda data, **kwargs: {
					**data,
					'genre': data.get('genre', 'Fantasy'),
					'normalized_title': data['title'],
					'normalized_author': data['author'],
					'genre_confidence': 1.0,
					'quality_score': 1.0,
					'is_flagged': False,
				}

				result = process_csv_import(temp_path, 'duplicate.csv', fake_user, fake_job)

			self.assertIs(result, fake_job)
			self.assertEqual(fake_job.total_rows, 2)
			self.assertEqual(fake_job.cleaned_count, 1)
			self.assertEqual(fake_job.duplicate_count, 1)
			self.assertEqual(fake_job.failed_count, 0)
			self.assertEqual(fake_manager.bulk_create.call_count, 1)
		finally:
			temp_path.unlink(missing_ok=True)

	# Malformed uploads should stop before import starts and return HTTP 400.
	def test_import_view_rejects_malformed_file(self):
		request = self.factory.post(reverse('import-list'), {}, format='multipart')
		force_authenticate(request, user=self.admin)

		response = ImportJobViewSet.as_view({'post': 'create'})(request)
		self.assertEqual(response.status_code, 400)

		request = self.factory.post(
			reverse('import-list'),
			{'file': SimpleUploadedFile('broken.txt', b'not csv')},
			format='multipart'
		)
		force_authenticate(request, user=self.admin)

		response = ImportJobViewSet.as_view({'post': 'create'})(request)
		self.assertEqual(response.status_code, 400)

	def test_management_command_passes_path_to_importer(self):
		fake_user = SimpleNamespace(username='admin')
		fake_job = SimpleNamespace(
			status='completed',
			file_name='sample.csv',
			total_rows=2,
			cleaned_count=2,
			duplicate_count=0,
			failed_count=0,
			error_log=[],
			completed_at=None,
			save=MagicMock(),
			refresh_from_db=MagicMock(),
		)

		with patch('books.management.commands.import_books.os.path.exists', return_value=True), \
			 patch('books.management.commands.import_books.User.objects.get', return_value=fake_user), \
			 patch('books.management.commands.import_books.ImportJob.objects.create', return_value=fake_job), \
			 patch('books.management.commands.import_books.process_csv_import') as mock_import:
			Command().handle(csv_path='data/books.csv', username='admin')

		mock_import.assert_called_once()
		self.assertEqual(mock_import.call_args.kwargs['file_content'], 'data/books.csv')
		self.assertEqual(mock_import.call_args.kwargs['file_name'], 'books.csv')

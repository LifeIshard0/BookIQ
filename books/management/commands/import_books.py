import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from books.models import ImportJob
from books.services.importer import process_csv_import

User = get_user_model()


class Command(BaseCommand):
    help = 'Import books from a local CSV file into the database.'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_path',
            type=str,
            help='Path to the CSV file to import'
        )
        parser.add_argument(
            '--username',
            type=str,
            default='admin',
            help='Username of the admin user to attribute imports to'
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        username = options['username']

        if not os.path.exists(csv_path):
            self.stderr.write(self.style.ERROR(f'File not found: {csv_path}'))
            return

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'User "{username}" not found.'))
            return

        self.stdout.write(f'Starting import from {csv_path}...')

        job = ImportJob.objects.create(
            status=ImportJob.Status.PENDING,
            file_name=os.path.basename(csv_path),
            created_by=user,
        )

        process_csv_import(
            file_content=csv_path,
            file_name=os.path.basename(csv_path),
            imported_by=user,
            job=job,
        )

        job.refresh_from_db()

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Import complete!'
            f'\n   Status:     {job.status}'
            f'\n   Total rows: {job.total_rows}'
            f'\n   Cleaned:    {job.cleaned_count}'
            f'\n   Duplicates: {job.duplicate_count}'
            f'\n   Failed:     {job.failed_count}'
        ))

        if job.error_log:
            self.stdout.write(
                self.style.WARNING(f'\n   First error: {job.error_log[0]}')
            )

from django.core.management.base import BaseCommand
from books.services.search import rebuild_all_search_vectors


class Command(BaseCommand):
    help = 'Rebuilds the PostgreSQL full-text search vector for all books.'

    def handle(self, *args, **options):
        self.stdout.write('Building search index...')
        count = rebuild_all_search_vectors()
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Search index built for {count} books.'
            )
        )

import uuid
from django.db import models
from django.conf import settings
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.core.validators import MinValueValidator, MaxValueValidator


class Book(models.Model):
    # --- Identity ---
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    # --- Raw fields (as ingested) ---
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=300)
    isbn_13 = models.CharField(max_length=13, unique=True, null=True, blank=True)
    description = models.TextField(blank=True, default='')
    genre = models.CharField(max_length=100, blank=True, default='')
    published_year = models.IntegerField(null=True, blank=True)
    publisher = models.CharField(max_length=300, blank=True, default='')
    page_count = models.IntegerField(null=True, blank=True)
    language = models.CharField(max_length=10, default='en')
    cover_url = models.URLField(blank=True, default='')

    # --- Cleaned/normalised fields (data provenance) ---
    normalized_title = models.CharField(max_length=500, blank=True, default='')
    normalized_author = models.CharField(max_length=300, blank=True, default='')

    # --- Intelligence fields ---
    quality_score = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    is_flagged = models.BooleanField(default=False)
    genre_confidence = models.FloatField(default=0.0)

    # --- Aggregated rating fields (updated via signals) ---
    average_rating = models.FloatField(default=0.0)
    rating_count = models.IntegerField(default=0)
    upvote_count = models.IntegerField(default=0)
    downvote_count = models.IntegerField(default=0)

    # --- Provenance ---
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='books_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['genre']),
            models.Index(fields=['quality_score']),
            models.Index(fields=['is_flagged']),
            models.Index(fields=['average_rating']),
        ]

    def __str__(self):
        return f"{self.title} — {self.author}"

    def update_rating_aggregates(self):
        """Recompute all rating aggregates from BookRating records."""
        from django.db.models import Avg, Count
        ratings = self.ratings.all()
        total = ratings.count()
        if total == 0:
            self.average_rating = 0.0
            self.rating_count = 0
            self.upvote_count = 0
            self.downvote_count = 0
        else:
            agg = ratings.aggregate(avg=Avg('rating'), count=Count('id'))
            self.average_rating = round(agg['avg'], 2)
            self.rating_count = agg['count']
            self.upvote_count = ratings.filter(rating__gte=4).count()
            self.downvote_count = ratings.filter(rating__lte=2).count()
        self.save(update_fields=[
            'average_rating', 'rating_count',
            'upvote_count', 'downvote_count'
        ])


class BookRating(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name='ratings'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ratings'
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    review = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('book', 'user')  # One rating per user per book
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} rated '{self.book.title}' {self.rating}/5"

    @property
    def vote_type(self):
        if self.rating is None:
            return 'neutral'
        if self.rating >= 4:
            return 'upvote'
        elif self.rating <= 2:
            return 'downvote'
        return 'neutral'


class ImportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    file_name = models.CharField(max_length=255, blank=True, default='')
    total_rows = models.IntegerField(default=0)
    cleaned_count = models.IntegerField(default=0)
    duplicate_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='import_jobs'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ImportJob {self.id} — {self.status} ({self.cleaned_count} cleaned)"


# --- Signals: keep Book rating aggregates in sync automatically ---

@receiver(post_save, sender=BookRating)
def update_book_on_rating_save(sender, instance, **kwargs):
    instance.book.update_rating_aggregates()


@receiver(post_delete, sender=BookRating)
def update_book_on_rating_delete(sender, instance, **kwargs):
    instance.book.update_rating_aggregates()

@receiver(pre_save, sender=Book)
def run_pipeline_on_book_save(sender, instance, **kwargs):
    """
    Runs the 6-step cleaning pipeline before every Book save.
    Populates: normalized_title, normalized_author, genre,
    genre_confidence, quality_score, is_flagged.
    """
    from books.services.cleaning import run_cleaning_pipeline

    book_data = {
        'title': instance.title,
        'author': instance.author,
        'isbn_13': instance.isbn_13,
        'description': instance.description,
        'genre': instance.genre,
        'published_year': instance.published_year,
        'publisher': instance.publisher,
        'page_count': instance.page_count,
    }

    cleaned = run_cleaning_pipeline(
        book_data,
        book_id=instance.pk if instance.pk else None
    )

    instance.genre = cleaned.get('genre', instance.genre)
    instance.normalized_title = cleaned.get('normalized_title', '')
    instance.normalized_author = cleaned.get('normalized_author', '')
    instance.genre_confidence = cleaned.get('genre_confidence', 0.0)
    instance.quality_score = cleaned.get('quality_score', 0.0)
    instance.is_flagged = cleaned.get('is_flagged', False)

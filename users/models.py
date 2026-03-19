import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        READER = 'reader', 'Reader'
        CURATOR = 'curator', 'Curator'
        ADMIN = 'admin', 'Admin'

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.READER
    )
    bio = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.username} ({self.role})"

    @property
    def is_curator_or_above(self):
        return self.role in [self.Role.CURATOR, self.Role.ADMIN]

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

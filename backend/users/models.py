# User model placeholder
from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    phone_number = models.CharField(max_length=15, unique=True)
    location = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.username} - {self.phone_number}"
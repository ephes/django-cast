from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class SeedUserManager(BaseUserManager):
    def create_user(self, handle, password=None, **fields):
        user = self.model(handle=handle, **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class SeedUser(AbstractUser):
    username = None
    handle = models.CharField(max_length=100, unique=True)
    USERNAME_FIELD = "handle"
    accounts = SeedUserManager()

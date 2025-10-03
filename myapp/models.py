from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager,
)
from django.utils import timezone

# Encrypted field for api_key (django-fernet-fields). Falls back to CharField if not installed.
try:
    from fernet_fields import EncryptedTextField  # pip install django-fernet-fields
except Exception:  # pragma: no cover
    EncryptedTextField = None


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("El email es obligatorio")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.BigAutoField(primary_key=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=30, blank=True)
    if EncryptedTextField is not None:
        api_key = EncryptedTextField(blank=True, null=True, help_text="Clave API cifrada para búsquedas")
    else:
        api_key = models.CharField(max_length=255, blank=True, help_text="Clave API (instala django-fernet-fields para cifrar)")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self) -> str:
        return self.email


class Search(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("running", "Running"),
        ("done", "Done"),
        ("error", "Error"),
    )

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='searches')
    city = models.CharField(max_length=120)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    category = models.CharField(max_length=120)
    # ISO 3166-1 alpha-2 country code (ej: 'ES', 'US')
    country = models.CharField(max_length=2, default='ES')
    job_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        cp = self.postal_code or "-"
        return f"{self.category} @ {self.city} {cp} ({self.status})"

# Create your models here.

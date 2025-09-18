from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator


class Business(models.Model):
    """
    Modelo para almacenar información de negocios encontrados
    """
    name = models.CharField(max_length=200, verbose_name="Nombre del negocio")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono")
    email = models.EmailField(blank=True, null=True, verbose_name="Correo electrónico")
    address = models.TextField(blank=True, null=True, verbose_name="Dirección")
    postal_code = models.CharField(
        max_length=5, 
        validators=[RegexValidator(r'^\d{5}$', 'Código postal debe tener exactamente 5 dígitos')],
        verbose_name="Código postal"
    )
    niche = models.CharField(max_length=100, verbose_name="Nicho de negocio")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")
    
    class Meta:
        verbose_name = "Negocio"
        verbose_name_plural = "Negocios"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.postal_code}"


class SearchHistory(models.Model):
    """
    Modelo para registrar las búsquedas realizadas por los usuarios
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        verbose_name="Usuario"
    )
    postal_code = models.CharField(
        max_length=5, 
        validators=[RegexValidator(r'^\d{5}$', 'Código postal debe tener exactamente 5 dígitos')],
        verbose_name="Código postal"
    )
    niche = models.CharField(max_length=100, verbose_name="Nicho de negocio")
    results_count = models.IntegerField(default=0, verbose_name="Número de resultados")
    excel_file = models.FileField(
        upload_to='exports/', 
        blank=True, 
        null=True, 
        verbose_name="Archivo Excel generado"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de búsqueda")
    
    class Meta:
        verbose_name = "Historial de búsqueda"
        verbose_name_plural = "Historial de búsquedas"
        ordering = ['-created_at']
    
    def __str__(self):
        user_info = f"{self.user.username}" if self.user else "Usuario anónimo"
        return f"{user_info} - {self.postal_code} ({self.niche})"


class BusinessNiche(models.Model):
    """
    Modelo para definir los nichos de negocio disponibles
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="Nombre del nicho")
    description = models.TextField(blank=True, verbose_name="Descripción")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Nicho de negocio"
        verbose_name_plural = "Nichos de negocio"
        ordering = ['name']
    
    def __str__(self):
        return self.name

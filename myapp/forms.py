from django import forms
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from .models import BusinessNiche
import requests
import json


def validate_spanish_postal_code(value):
    """
    Valida que el código postal existe en España
    """
    if not value or len(value) != 5:
        raise ValidationError('El código postal debe tener exactamente 5 dígitos.')
    
    # Lista de códigos postales españoles válidos (rangos principales)
    valid_ranges = [
        (1000, 5299),   # Madrid
        (8000, 8999),   # Barcelona
        (10000, 14999), # Andalucía
        (15000, 15999), # Galicia
        (20000, 20999), # País Vasco
        (22000, 22999), # Aragón
        (24000, 24999), # Castilla y León
        (25000, 25999), # Cataluña
        (26000, 26999), # La Rioja
        (28000, 28999), # Madrid
        (30000, 30999), # Murcia
        (31000, 31999), # Navarra
        (32000, 32999), # Galicia
        (33000, 33999), # Asturias
        (34000, 34999), # Castilla y León
        (35000, 35999), # Canarias
        (36000, 36999), # Galicia
        (37000, 37999), # Castilla y León
        (38000, 38999), # Canarias
        (39000, 39999), # Cantabria
        (40000, 40999), # Castilla y León
        (41000, 41999), # Andalucía
        (42000, 42999), # Castilla y León
        (43000, 43999), # Cataluña
        (44000, 44999), # Aragón
        (45000, 45999), # Castilla-La Mancha
        (46000, 46999), # Comunidad Valenciana
        (47000, 47999), # Castilla y León
        (48000, 48999), # País Vasco
        (49000, 49999), # Castilla y León
        (50000, 50999), # Aragón
        (51000, 51999), # Andalucía
        (52000, 52999), # Madrid
    ]
    
    code = int(value)
    is_valid = any(start <= code <= end for start, end in valid_ranges)
    
    if not is_valid:
        raise ValidationError('El código postal no corresponde a España.')


class BusinessSearchForm(forms.Form):
    """
    Formulario para búsqueda de negocios por código postal y nicho
    """
    postal_code = forms.CharField(
        max_length=5,
        validators=[
            RegexValidator(r'^\d{5}$', 'El código postal debe tener exactamente 5 dígitos'),
            validate_spanish_postal_code
        ],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: 28001',
            'pattern': '[0-9]{5}',
            'maxlength': '5'
        }),
        label='Código Postal',
        help_text='Introduce un código postal español de 5 dígitos'
    )
    
    niche = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        label='Tipo de Negocio',
        help_text='Selecciona el tipo de negocio que buscas'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cargar nichos desde la base de datos
        niches = BusinessNiche.objects.filter(is_active=True).order_by('name')
        self.fields['niche'].choices = [('', 'Selecciona un tipo de negocio')] + [(niche.name, niche.name) for niche in niches]
    
    def clean_postal_code(self):
        """
        Limpia y valida el código postal
        """
        postal_code = self.cleaned_data.get('postal_code', '').strip()
        
        # Validar formato
        if not postal_code.isdigit():
            raise ValidationError('El código postal debe contener solo números.')
        
        if len(postal_code) != 5:
            raise ValidationError('El código postal debe tener exactamente 5 dígitos.')
        
        return postal_code
    
    def clean_niche(self):
        """
        Valida que se seleccione un nicho válido
        """
        niche = self.cleaned_data.get('niche')
        if not niche:
            raise ValidationError('Debes seleccionar un tipo de negocio.')
        return niche


class BusinessNicheForm(forms.ModelForm):
    """
    Formulario para gestionar nichos de negocio (admin)
    """
    class Meta:
        model = BusinessNiche
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

from django import forms

# Intentar usar pycountry para obtener la lista completa de países
try:
    import pycountry
    COUNTRY_CHOICES = sorted([(c.alpha_2, f"{c.name} ({c.alpha_2})") for c in pycountry.countries], key=lambda x: x[1])
except Exception:
    # Fallback con algunos países comunes y ES por defecto
    COUNTRY_CHOICES = [
        ('ES', 'Spain (ES)'),
        ('US', 'United States (US)'),
        ('GB', 'United Kingdom (GB)'),
        ('FR', 'France (FR)'),
        ('DE', 'Germany (DE)'),
    ]


class SearchForm(forms.Form):
    postal_code = forms.CharField(label='Código postal', max_length=10, widget=forms.TextInput(attrs={'placeholder': '28001'}))
    category = forms.CharField(label='Categoría', max_length=120, widget=forms.TextInput(attrs={'placeholder': 'p. ej. peluquería'}))
    country = forms.ChoiceField(label='País', choices=COUNTRY_CHOICES, initial='ES')

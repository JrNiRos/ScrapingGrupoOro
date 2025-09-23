from django import forms

# Lista específica de países para el buscador de negocios
COUNTRY_CHOICES = [
    ('ES', 'España (ES)'),
    ('FR', 'Francia (FR)'),
    ('DE', 'Alemania (DE)'),
    ('IT', 'Italia (IT)'),
    ('BE', 'Bélgica (BE)'),
    ('PT', 'Portugal (PT)'),
]


class SearchForm(forms.Form):
    postal_code = forms.CharField(label='Código postal', max_length=10, widget=forms.TextInput(attrs={'placeholder': '28001'}))
    category = forms.CharField(label='Categoría', max_length=120, widget=forms.TextInput(attrs={'placeholder': 'p. ej. peluquería'}))
    country = forms.ChoiceField(label='País', choices=COUNTRY_CHOICES, initial='ES')

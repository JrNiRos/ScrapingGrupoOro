from django.core.management.base import BaseCommand
from myapp.models import BusinessNiche


class Command(BaseCommand):
    help = 'Crea nichos de negocio predefinidos'

    def handle(self, *args, **options):
        niches = [
            'Peluquería',
            'Bar',
            'Restaurante',
            'Tienda',
            'Farmacia',
            'Supermercado',
            'Panadería',
            'Carnicería',
            'Pescadería',
            'Frutas y Verduras',
            'Optic',
            'Dentista',
            'Médico',
            'Veterinario',
            'Gasolinera',
            'Taller mecánico',
            'Lavandería',
            'Floristería',
            'Librería',
            'Papelería',
            'Electrodomésticos',
            'Ropa',
            'Zapatería',
            'Joyería',
            'Relojería',
            'Óptica',
            'Centro deportivo',
            'Gimnasio',
            'Peluquería canina',
            'Veterinaria',
            'Hotel',
            'Hostal',
            'Cafetería',
            'Pastelería',
            'Heladería',
            'Tapas',
            'Pizzería',
            'Hamburguesería',
            'Kebab',
            'Sushi',
            'Comida china',
            'Comida italiana',
            'Comida mexicana',
            'Comida india',
            'Comida japonesa',
            'Comida árabe',
            'Comida vegetariana',
            'Comida vegana',
            'Comida rápida',
            'Comida a domicilio',
        ]

        created_count = 0
        for niche_name in niches:
            niche, created = BusinessNiche.objects.get_or_create(
                name=niche_name,
                defaults={'description': f'Negocios de {niche_name.lower()}'}
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Creado nicho: {niche_name}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Se crearon {created_count} nichos nuevos')
        )

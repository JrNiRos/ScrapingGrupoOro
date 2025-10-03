from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0003_search_country'),
    ]

    operations = [
        migrations.AddField(
            model_name='search',
            name='city',
            field=models.CharField(max_length=120, default=''),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='search',
            name='postal_code',
            field=models.CharField(max_length=10, null=True, blank=True),
        ),
    ]

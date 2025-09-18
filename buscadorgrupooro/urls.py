"""
URL configuration for buscadorgrupooro project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from myapp.views import (
    home, start_scrape, download_excel, job_status,
    business_search, download_search_excel, search_results
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('scrape/', start_scrape, name='start_scrape'),
    path('status/<str:job_id>/', job_status, name='job_status'),
    path('download/<str:job_id>/', download_excel, name='download_excel'),
    
    # Nuevas rutas para búsqueda de negocios
    path('business-search/', business_search, name='business_search'),
    path('search-results/<str:job_id>/', search_results, name='search_results'),
    path('download-search/<int:search_id>/', download_search_excel, name='download_search_excel'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

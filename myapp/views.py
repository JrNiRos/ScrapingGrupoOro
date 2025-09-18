from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest, HttpResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
import uuid
import json
import os
import time
import requests
from openpyxl import Workbook
from threading import Thread
from .models import Business, SearchHistory, BusinessNiche
from .forms import BusinessSearchForm

# In-memory job registry (simple demo)
JOBS = {}


@ensure_csrf_cookie
def home(request):
    return render(request, "myapp/home.html")


def business_search(request):
    """
    Vista para la búsqueda de negocios por código postal y nicho
    """
    if request.method == 'POST':
        form = BusinessSearchForm(request.POST)
        if form.is_valid():
            postal_code = form.cleaned_data['postal_code']
            niche = form.cleaned_data['niche']
            
            # Crear registro de búsqueda
            search_record = SearchHistory.objects.create(
                user=request.user if request.user.is_authenticated else None,
                postal_code=postal_code,
                niche=niche,
                results_count=0
            )
            
            # Iniciar búsqueda en segundo plano
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {
                'status': 'pending',
                'error': None,
                'search_id': search_record.id
            }
            
            def search_worker():
                try:
                    JOBS[job_id]['status'] = 'running'
                    
                    # Realizar búsqueda de negocios
                    businesses = search_businesses_by_postal_and_niche(postal_code, niche)
                    
                    # Guardar resultados en la base de datos
                    with transaction.atomic():
                        for business_data in businesses:
                            Business.objects.create(
                                name=business_data['name'],
                                phone=business_data.get('phone', ''),
                                email=business_data.get('email', ''),
                                address=business_data.get('address', ''),
                                postal_code=postal_code,
                                niche=niche
                            )
                        
                        # Actualizar el registro de búsqueda
                        search_record.results_count = len(businesses)
                        
                        # Generar archivo Excel
                        excel_content = generate_business_excel(businesses, postal_code, niche)
                        filename = f"negocios_{postal_code}_{niche}_{job_id}.xlsx"
                        search_record.excel_file.save(
                            filename,
                            ContentFile(excel_content),
                            save=True
                        )
                    
                    JOBS[job_id]['status'] = 'done'
                    JOBS[job_id]['results_count'] = len(businesses)
                    
                except Exception as e:
                    JOBS[job_id]['status'] = 'error'
                    JOBS[job_id]['error'] = str(e)
            
            Thread(target=search_worker, daemon=True).start()
            
            messages.success(request, f'Búsqueda iniciada para código postal {postal_code} y nicho {niche}.')
            return JsonResponse({'job_id': job_id})
        else:
            return JsonResponse({'errors': form.errors}, status=400)
    else:
        form = BusinessSearchForm()
    
    # Obtener búsquedas recientes del usuario
    recent_searches = []
    if request.user.is_authenticated:
        recent_searches = SearchHistory.objects.filter(user=request.user)[:5]
    
    context = {
        'form': form,
        'recent_searches': recent_searches
    }
    return render(request, 'myapp/business_search.html', context)


@require_POST
def start_scrape(request):
    # Expect JSON body: {"location": "Madrid"}
    try:
        body = json.loads(request.body.decode("utf-8"))
        location = body.get("location", "").strip()
        # default to max allowed by Serper single request
        limit = 100
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    if not location:
        return HttpResponseBadRequest("La ubicación es obligatoria")
    # Clamp for safety
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    # Create a job id and placeholder output path
    job_id = uuid.uuid4().hex
    out_dir = os.path.join(settings.MEDIA_ROOT, "exports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"scrape_{job_id}.xlsx")

    JOBS[job_id] = {"status": "pending", "error": None}

    def worker():
        try:
            JOBS[job_id]["status"] = "running"
            data_by_area = scrape_businesses_serper(location, limit)
            # Ensure at least one sheet
            if not data_by_area:
                data_by_area = {"Sin datos": []}
            export_to_excel(data_by_area, out_path)
            JOBS[job_id]["status"] = "done"
        except Exception as e:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)

    Thread(target=worker, daemon=True).start()

    return JsonResponse({"job_id": job_id})


def job_status(request, job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JsonResponse({"status": "unknown"}, status=404)
    payload = {"status": job["status"], "error": job["error"]}
    if job["status"] == "done":
        payload["download_url"] = f"/download/{job_id}/"
    return JsonResponse(payload)


def download_excel(request, job_id: str):
    file_path = os.path.join(settings.MEDIA_ROOT, "exports", f"scrape_{job_id}.xlsx")
    if not os.path.exists(file_path):
        return HttpResponseBadRequest("Archivo no encontrado o aún en proceso")
    return FileResponse(open(file_path, "rb"), as_attachment=True, filename=f"resultados_{job_id}.xlsx")


def scrape_businesses_serper(location_query: str, limit: int = 20):
    """
    Uses Serper (Google Local) to get businesses for a given Spanish location.
    Returns a dict grouped under a single sheet name.
    """
    api_key = getattr(settings, "SERPER_API_KEY", None)
    if not api_key:
        raise RuntimeError("Falta SERPER_API_KEY en settings")

    url = "https://google.serper.dev/places"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    # Fetch multiple batches. Some Serper plans cap results ~10 and ignore paging.
    # We diversify the query with modifiers to expand coverage and then deduplicate.
    aggregated: list[dict] = []
    seen_keys = set()
    per_batch = min(100, max(10, limit))
    query_modifiers = [
        "",
        "centro",
        "norte",
        "sur",
        "este",
        "oeste",
        "a",
        "b",
        "c",
        "d",
        "e",
        "1",
        "2",
        "3",
    ]

    for mod in query_modifiers:
        q = f"negocios en {location_query} {mod}".strip()
        payload = {"q": q, "gl": "es", "hl": "es", "num": per_batch}
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=45)
        if r.status_code == 401:
            raise RuntimeError("API key de Serper inválida o sin permisos")
        # Some plans return 404 for unsupported params; just continue to next mod
        if r.status_code == 404:
            continue
        r.raise_for_status()
        data = r.json()
        results = data.get("places") or data.get("localResults") or data.get("placeResults") or []
        for item in results:
            name = item.get("title") or item.get("name")
            phone = item.get("phoneNumber") or item.get("phone")
            website = item.get("website")
            address = item.get("address") or item.get("streetAddress") or item.get("fullAddress")
            dedup_key = f"{(name or '').strip().lower()}|{(address or '').strip().lower()}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            aggregated.append({
                "name": name or "-",
                "phone": phone or "-",
                "email": "-",
                "address": address or (website or "-"),
            })
            if len(aggregated) >= limit:
                break
        if len(aggregated) >= limit:
            break

    if not aggregated:
        return {}

    return {"Resultados": aggregated[:limit]}


def fetch_pois_by_area(area_id: int, headers: dict):
    # Fetch amenities with phone/email; group by district if available
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:60];
    area({area_id})->.searchArea;
    (
      nwr["amenity"]["name"](area.searchArea);
    );
    out tags center;
    """
    r = requests.post(overpass_url, data={"data": query}, headers=headers, timeout=90)
    r.raise_for_status()
    data = r.json()

    groups = {}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        phone = tags.get("phone") or tags.get("contact:phone")
        email = tags.get("email") or tags.get("contact:email")
        street = tags.get("addr:street")
        housenumber = tags.get("addr:housenumber")
        city = tags.get("addr:city")
        district = tags.get("addr:suburb") or tags.get("addr:district") or "Sin barrio"
        address = ", ".join(filter(None, [street, housenumber, city]))

        group_key = district
        groups.setdefault(group_key, []).append({
            "name": name,
            "phone": phone or "-",
            "email": email or "-",
            "address": address or "-",
        })
    return groups


def fetch_pois_by_radius(lat: float, lon: float, headers: dict):
    overpass_url = "https://overpass-api.de/api/interpreter"
    # 5km radius demo
    query = f"""
    [out:json][timeout:60];
    (
      nwr(around:5000,{lat},{lon})["amenity"]["name"];
    );
    out tags center;
    """
    r = requests.post(overpass_url, data={"data": query}, headers=headers, timeout=90)
    r.raise_for_status()
    data = r.json()

    groups = {"Zona": []}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        phone = tags.get("phone") or tags.get("contact:phone")
        email = tags.get("email") or tags.get("contact:email")
        street = tags.get("addr:street")
        housenumber = tags.get("addr:housenumber")
        city = tags.get("addr:city")
        address = ", ".join(filter(None, [street, housenumber, city]))
        groups["Zona"].append({
            "name": name,
            "phone": phone or "-",
            "email": email or "-",
            "address": address or "-",
        })
    return groups


def export_to_excel(groups: dict, file_path: str):
    wb = Workbook()
    # Remove the default sheet
    default_ws = wb.active
    wb.remove(default_ws)

    for group_name, rows in groups.items():
        ws = wb.create_sheet(title=str(group_name)[:31])
        ws.append(["Nombre", "Teléfono", "Email", "Dirección"])
        for item in rows:
            ws.append([item["name"], item["phone"], item["email"], item["address"]])

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    wb.save(file_path)


def search_businesses_by_postal_and_niche(postal_code, niche):
    """
    Busca negocios usando código postal y nicho específico
    """
    api_key = getattr(settings, "SERPER_API_KEY", None)
    if not api_key:
        raise RuntimeError("Falta SERPER_API_KEY en settings")

    url = "https://google.serper.dev/places"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    
    # Construir query específica para España
    query = f"{niche} código postal {postal_code} España"
    
    payload = {
        "q": query,
        "gl": "es",  # España
        "hl": "es",  # Español
        "num": 50
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        
        if response.status_code == 401:
            raise RuntimeError("API key de Serper inválida o sin permisos")
        
        response.raise_for_status()
        data = response.json()
        
        results = data.get("places") or data.get("localResults") or data.get("placeResults") or []
        
        businesses = []
        seen_businesses = set()
        
        for item in results:
            name = item.get("title") or item.get("name", "")
            phone = item.get("phoneNumber") or item.get("phone", "")
            website = item.get("website", "")
            address = item.get("address") or item.get("streetAddress") or item.get("fullAddress", "")
            
            # Verificar que el negocio tenga nombre y que no esté duplicado
            if name and name.strip():
                business_key = f"{name.strip().lower()}|{address.strip().lower()}"
                if business_key not in seen_businesses:
                    seen_businesses.add(business_key)
                    
                    # Intentar extraer email del website si es posible
                    email = extract_email_from_website(website) if website else ""
                    
                    businesses.append({
                        "name": name.strip(),
                        "phone": phone.strip() if phone else "",
                        "email": email,
                        "address": address.strip() if address else "",
                        "website": website
                    })
        
        return businesses
        
    except requests.RequestException as e:
        raise RuntimeError(f"Error al conectar con la API: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Error en la búsqueda: {str(e)}")


def extract_email_from_website(website):
    """
    Intenta extraer un email de un sitio web (función básica)
    """
    if not website:
        return ""
    
    try:
        # Aquí podrías implementar scraping del sitio web para encontrar emails
        # Por simplicidad, retornamos vacío por ahora
        return ""
    except:
        return ""


def generate_business_excel(businesses, postal_code, niche):
    """
    Genera un archivo Excel con los resultados de la búsqueda
    """
    wb = Workbook()
    ws = wb.active
    ws.title = f"Negocios {niche}"
    
    # Encabezados
    headers = ["Nombre", "Teléfono", "Email", "Dirección", "Sitio Web"]
    for col, header in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=header)
    
    # Datos
    for row, business in enumerate(businesses, 2):
        ws.cell(row=row, column=1, value=business.get("name", ""))
        ws.cell(row=row, column=2, value=business.get("phone", ""))
        ws.cell(row=row, column=3, value=business.get("email", ""))
        ws.cell(row=row, column=4, value=business.get("address", ""))
        ws.cell(row=row, column=5, value=business.get("website", ""))
    
    # Ajustar ancho de columnas
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width
    
    # Guardar en memoria
    from io import BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def download_search_excel(request, search_id):
    """
    Descarga el archivo Excel de una búsqueda específica
    """
    search_record = get_object_or_404(SearchHistory, id=search_id)
    
    if not search_record.excel_file:
        messages.error(request, "No se encontró el archivo Excel para esta búsqueda.")
        return HttpResponseBadRequest("Archivo no encontrado")
    
    filename = f"negocios_{search_record.postal_code}_{search_record.niche}.xlsx"
    return FileResponse(
        search_record.excel_file.open(),
        as_attachment=True,
        filename=filename
    )


def search_results(request, job_id):
    """
    Vista para mostrar los resultados de una búsqueda
    """
    job = JOBS.get(job_id)
    if not job:
        messages.error(request, "Búsqueda no encontrada.")
        return render(request, 'myapp/business_search.html')
    
    if job['status'] == 'done':
        search_record = get_object_or_404(SearchHistory, id=job.get('search_id'))
        businesses = Business.objects.filter(
            postal_code=search_record.postal_code,
            niche=search_record.niche
        )
        
        context = {
            'search_record': search_record,
            'businesses': businesses,
            'job_id': job_id
        }
        return render(request, 'myapp/search_results.html', context)
    
    # Si la búsqueda aún está en proceso, mostrar estado
    context = {
        'job_status': job['status'],
        'job_error': job.get('error'),
        'job_id': job_id
    }
    return render(request, 'myapp/search_loading.html', context)
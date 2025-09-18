from django.shortcuts import render
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import ensure_csrf_cookie
import uuid
import json
import os
import time
import requests
from openpyxl import Workbook
from threading import Thread

# In-memory job registry (simple demo)
JOBS = {}


@ensure_csrf_cookie
def home(request):
    return render(request, "myapp/home.html")


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
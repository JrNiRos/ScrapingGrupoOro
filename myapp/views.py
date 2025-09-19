from django.shortcuts import render
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import uuid
import json
import os
import time
import requests
from openpyxl import Workbook
from threading import Thread
from django import forms
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from .models import User, Search

# In-memory job registry (simple demo)
JOBS = {}


@ensure_csrf_cookie
@login_required
def home(request):
    if not (getattr(request.user, 'api_key', None)):
        from django.shortcuts import redirect
        return redirect('profile')
    return render(request, "myapp/home.html")


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["email"]
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'w-full rounded-xl bg-white/5 border border-white/10 p-3 text-white', 'placeholder': 'Email'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email").lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este email ya está registrado")
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Autologin opcional tras registro
            login(request, user)
            messages.success(request, 'Registro completado. Bienvenido/a.')
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "redirect": "/profile/"})
            from django.shortcuts import redirect
            # Tras registro, dirigir al usuario al perfil para que configure su API Key
            return redirect("profile")
    else:
        form = RegisterForm()
    return render(request, "auth/register.html", {"form": form})


def logout_view(request):
    """Logout vía GET y redirige al login."""
    logout(request)
    from django.shortcuts import redirect
    return redirect('login')


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone_number", "api_key"]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'w-full rounded-xl bg-white/5 border border-white/10 p-3 text-white'}),
            'last_name': forms.TextInput(attrs={'class': 'w-full rounded-xl bg-white/5 border border-white/10 p-3 text-white'}),
            'phone_number': forms.TextInput(attrs={'class': 'w-full rounded-xl bg-white/5 border border-white/10 p-3 text-white'}),
            'api_key': forms.TextInput(attrs={'class': 'w-full rounded-xl bg-white/5 border border-white/10 p-3 text-white'}),
        }


@login_required
def profile(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil actualizado correctamente')
            from django.shortcuts import redirect
            return redirect('home')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "auth/profile.html", {"form": form})


@require_POST
@login_required
def start_scrape(request):
    # Expect JSON body: {"location": "Madrid"}
    try:
        body = json.loads(request.body.decode("utf-8"))
        # Accept postal codes containing spaces or hyphens; keep only digits
        raw_postal = (body.get("postal_code") or "")
        postal_code = ''.join(ch for ch in raw_postal if ch.isdigit())[:5]
        category = (body.get("category") or "").strip()
        limit = 100
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    if not postal_code or not category:
        return HttpResponseBadRequest("El código postal y la categoría son obligatorios")
    import re
    if not re.fullmatch(r"\d{5}", postal_code):
        return HttpResponseBadRequest("El código postal debe tener 5 dígitos (España)")
    # Comprueba que los dos primeros dígitos (prefijo provincial) corresponden a España (01-52)
    try:
        province = int(postal_code[:2])
    except Exception:
        return HttpResponseBadRequest("Código postal inválido")
    if province < 1 or province > 52:
        return HttpResponseBadRequest("El código postal debe pertenecer a España (prefijo 01–52)")
    # Clamp for safety
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    # Require api_key on user
    if not (getattr(request.user, 'api_key', None)):
        return HttpResponseBadRequest("Debes configurar tu API Key en el perfil")

    # Create a job id and placeholder output path
    job_id = uuid.uuid4().hex
    out_dir = os.path.join(settings.MEDIA_ROOT, "exports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"scrape_{job_id}.xlsx")

    JOBS[job_id] = {"status": "pending", "error": None}

    # Persist the search tied to the user
    search = Search.objects.create(
        user=request.user,
        postal_code=postal_code,
        category=category,
        job_id=job_id,
        status="pending",
    )

    # Choose API key: user-specific if provided, else global fallback
    effective_api_key = getattr(request.user, 'api_key', None) or getattr(settings, 'SERPER_API_KEY', None)

    def worker():
        try:
            JOBS[job_id]["status"] = "running"
            data_by_area = scrape_businesses_by_cp_and_category(postal_code, category, limit, effective_api_key)
            # Ensure at least one sheet
            if not data_by_area:
                data_by_area = {"Sin datos": []}
            export_to_excel(data_by_area, out_path)
            JOBS[job_id]["status"] = "done"
            try:
                Search.objects.filter(id=search.id).update(status="done", finished_at=timezone.now())
            except Exception:
                pass
        except Exception as e:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)
            try:
                Search.objects.filter(id=search.id).update(status="error", error_message=str(e), finished_at=timezone.now())
            except Exception:
                pass

    Thread(target=worker, daemon=True).start()

    return JsonResponse({"job_id": job_id})


@login_required
def job_status(request, job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JsonResponse({"status": "unknown"}, status=404)
    payload = {"status": job["status"], "error": job["error"]}
    if job["status"] == "done":
        payload["download_url"] = f"/download/{job_id}/"
    return JsonResponse(payload)


@login_required
def download_excel(request, job_id: str):
    file_path = os.path.join(settings.MEDIA_ROOT, "exports", f"scrape_{job_id}.xlsx")
    if not os.path.exists(file_path):
        return HttpResponseBadRequest("Archivo no encontrado o aún en proceso")
    return FileResponse(open(file_path, "rb"), as_attachment=True, filename=f"resultados_{job_id}.xlsx")


def scrape_businesses_by_cp_and_category(postal_code: str, category: str, limit: int = 20, api_key: str | None = None):
    """Ejemplo de scraping/consulta por CP + categoría usando Serper (Google Local).
    Usa la api_key del usuario.
    """
    # Usa la api_key del usuario autenticado si existe; si no, fallback a settings
    # No necesitamos el usuario aquí; dejar explícitamente None
    request_user = None
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
    query_modifiers = ["", "centro", "norte", "sur"]

    for mod in query_modifiers:
        q = f"{category} {postal_code} {mod}".strip()
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
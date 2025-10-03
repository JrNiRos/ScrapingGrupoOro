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
import re
from openpyxl import Workbook
from threading import Thread
from django import forms
from .forms import SearchForm
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from .models import User, Search
from .utils import postal as postal_utils

# In-memory job registry (simple demo)
JOBS = {}


def fetch_email_from_website(url: str, timeout: int = 8) -> str | None:
    """Intenta extraer un email desde la página indicada.
    - Normaliza la URL añadiendo esquema si falta.
    - Busca primero enlaces mailto:, si no encuentra busca con regex en el HTML.
    - Devuelve la primera dirección válida encontrada o None.
    """
    import re

    if not url:
        return None
    # Normalizar esquema
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url.lstrip("/")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; Bot/1.0)"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        html = r.text or ""
    except Exception:
        return None

    # Buscar mailto: primero
    m = re.search(r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", html, re.I)
    if m:
        return m.group(1).lower()

    # Buscar direcciones de correo en el HTML
    # Limitamos el tamaño buscado para evitar escanear megabytes innecesarios
    snippet = html[:200000]
    found = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", snippet)
    if not found:
        return None
    # Devolver la primera que no parezca un placeholder genérico vacio
    for e in found:
        e_l = e.lower()
        # Filtrar valores que son claramente parte de ejemplos o rutas
        if any(x in e_l for x in ("example.com", "domain.com", "test@test", "no-reply", "noreply")):
            continue
        return e_l
    return None


@ensure_csrf_cookie
@login_required
def home(request):
    # Pasar el formulario con la lista de países
    form = SearchForm()
    return render(request, "myapp/home.html", {"form": form})


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
    # Body esperado: {"city": "Madrid", "postal_code": "28001" (opcional), "category": "peluquería", "country": "ES"}
    try:
        body = json.loads(request.body.decode("utf-8"))
        city = (body.get("city") or "").strip()
        # Acepta CP con espacios/guiones; mantiene sólo dígitos salvo PT
        raw_postal = (body.get("postal_code") or "")
        postal_code = ''.join(ch for ch in raw_postal if ch.isdigit())[:10]
        category = (body.get("category") or "").strip()
        country = (body.get("country") or "ES").strip().upper()
        # Intentar obtener más resultados por búsqueda
        limit = 1000
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    if not city or not category:
        return HttpResponseBadRequest("La ciudad y la categoría son obligatorias")
    import re
    # Validación específica por país (sólo si se proporciona código postal)
    if postal_code:
        if country == 'ES':
            if not re.fullmatch(r"\d{5}", postal_code):
                return HttpResponseBadRequest("El código postal debe tener 5 dígitos (España)")
            try:
                province = int(postal_code[:2])
            except Exception:
                return HttpResponseBadRequest("Código postal inválido")
            if province < 1 or province > 52:
                return HttpResponseBadRequest("El código postal debe pertenecer a España (prefijo 01–52)")
        elif country == 'FR':
            if not re.fullmatch(r"\d{5}", postal_code):
                return HttpResponseBadRequest("El código postal debe tener 5 dígitos (Francia)")
        elif country == 'DE':
            if not re.fullmatch(r"\d{5}", postal_code):
                return HttpResponseBadRequest("El código postal debe tener 5 dígitos (Alemania)")
        elif country == 'IT':
            if not re.fullmatch(r"\d{5}", postal_code):
                return HttpResponseBadRequest("El código postal debe tener 5 dígitos (Italia)")
        elif country == 'BE':
            if not re.fullmatch(r"\d{4}", postal_code):
                return HttpResponseBadRequest("El código postal debe tener 4 dígitos (Bélgica)")
        elif country == 'PT':
            if not re.fullmatch(r"\d{4}-?\d{3}", postal_code):
                return HttpResponseBadRequest("El código postal debe tener formato XXXX-XXX (Portugal)")
        else:
            if len(postal_code) < 3 or len(postal_code) > 10:
                return HttpResponseBadRequest("Introduce un código postal válido para el país seleccionado")
    # Clamp for safety - aumentar límite máximo para más resultados
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000

    # Resolver API key: usuario o settings (fallback) con saneado de espacios
    user_api_key_raw = getattr(request.user, 'api_key', None)
    if isinstance(user_api_key_raw, str):
        user_api_key = user_api_key_raw.strip()
    elif user_api_key_raw is None:
        user_api_key = ''
    else:
        user_api_key = str(user_api_key_raw).strip()

    settings_api_key_raw = getattr(settings, 'SERPER_API_KEY', None)
    if isinstance(settings_api_key_raw, str):
        settings_api_key = settings_api_key_raw.strip()
    elif settings_api_key_raw is None:
        settings_api_key = ''
    else:
        settings_api_key = str(settings_api_key_raw).strip()

    effective_api_key = user_api_key or settings_api_key
    if not effective_api_key:
        return HttpResponseBadRequest("Falta API Key: configura tu clave en el perfil o en settings")

    # Create a job id and placeholder output path
    job_id = uuid.uuid4().hex
    out_dir = os.path.join(settings.MEDIA_ROOT, "exports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"scrape_{job_id}.xlsx")

    JOBS[job_id] = {"status": "pending", "error": None}

    # Persist the search tied to the user
    search = Search.objects.create(
        user=request.user,
        city=city,
        postal_code=(postal_code or None),
        category=category,
        country=country,
        job_id=job_id,
        status="pending",
    )

    # effective_api_key resuelto arriba

    def worker():
        try:
            JOBS[job_id]["status"] = "running"
            data_by_area = scrape_businesses_by_city_and_category(city, category, postal_code=(postal_code or None), limit=limit, api_key=effective_api_key, country=country)
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


def scrape_businesses_by_cp_and_category(postal_code: str, category: str, limit: int = 20, api_key: str | None = None, country: str = 'ES'):
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
    per_batch = min(100, max(25, limit // 3))  # Dividir en menos consultas pero más grandes
    # Ampliar estrategias de consulta para maximizar resultados
    base_modifiers = [
        "",  # Consulta base
        "centro", "norte", "sur", "este", "oeste",  # Zonas geográficas
        "cerca", "próximo", "local", "zona", "cercano", "alrededor",  # Proximidad
        "tienda", "negocio", "empresa", "comercio", "establecimiento",  # Comerciales
        "servicio", "profesional", "especialista", "proveedor"  # Servicios
    ]
    
    # Agregar modificadores específicos por país para mayor cobertura
    country_specific = []
    if country == 'ES':
        country_specific = ["barrio", "distrito", "municipio", "localidad", "pueblo"]
    elif country == 'FR':
        country_specific = ["quartier", "arrondissement", "commune", "ville"]
    elif country == 'DE':
        country_specific = ["stadtteil", "bezirk", "gemeinde", "stadt"]
    elif country == 'IT':
        country_specific = ["quartiere", "zona", "comune", "città"]
    elif country == 'BE':
        country_specific = ["wijk", "gemeente", "stad", "commune"]
    elif country == 'PT':
        country_specific = ["bairro", "freguesia", "concelho", "cidade"]
    
    query_modifiers = base_modifiers + country_specific
    # Cache local para emails por URL dentro de la misma ejecución (evita múltiples requests)
    email_cache: dict[str, str | None] = {}

    for mod in query_modifiers:
        # Construir consulta más específica incluyendo el país para mayor precisión
        country_name = ""
        if country == 'ES':
            country_name = "España"
        elif country == 'FR':
            country_name = "France"
        elif country == 'DE':
            country_name = "Germany"
        elif country == 'IT':
            country_name = "Italy"
        elif country == 'BE':
            country_name = "Belgium"
        elif country == 'PT':
            country_name = "Portugal"
        
        # Crear consultas más variadas para maximizar cobertura
        if mod == "":
            # Consulta base más específica
            q = f"{category} {postal_code} {country_name}".strip()
        elif mod in ["centro", "norte", "sur", "este", "oeste"]:
            # Consultas geográficas
            q = f"{category} {postal_code} {mod} {country_name}".strip()
        elif mod in ["cerca", "próximo", "local", "zona", "cercano", "alrededor"]:
            # Consultas de proximidad
            q = f"{category} {mod} {postal_code} {country_name}".strip()
        elif mod in ["tienda", "negocio", "empresa", "comercio", "establecimiento"]:
            # Consultas comerciales
            q = f"{mod} {category} {postal_code} {country_name}".strip()
        elif mod in ["servicio", "profesional", "especialista", "proveedor"]:
            # Consultas de servicio
            q = f"{category} {mod} código postal {postal_code} {country_name}".strip()
        else:
            # Modificadores específicos por país (barrio, quartier, stadtteil, etc.)
            q = f"{category} {mod} {postal_code} {country_name}".strip()
        
        # Usar el country ISO alpha-2 para parámetros regionales (gl) en Serper/Google local
        gl = (country or 'ES').lower()
        hl = 'es' if gl == 'es' else 'en'
        payload = {"q": q, "gl": gl, "hl": hl, "num": per_batch}
        
        # Reintentos para maximizar obtención de resultados
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=45)
                if r.status_code == 401:
                    raise RuntimeError("API key de Serper inválida o sin permisos")
                # Some plans return 404 for unsupported params; just continue to next mod
                if r.status_code == 404:
                    break
                if r.status_code == 429:  # Rate limit
                    if attempt < max_retries:
                        import time
                        time.sleep(2 ** attempt)  # Backoff exponencial
                        continue
                    else:
                        break
                r.raise_for_status()
                data = r.json()
                results = data.get("places") or data.get("localResults") or data.get("placeResults") or []
                break
            except Exception as e:
                if attempt < max_retries:
                    continue
                else:
                    # En caso de error, continuar con el siguiente modificador
                    results = []
                    break
        for item in results:
            name = item.get("title") or item.get("name")
            phone = item.get("phoneNumber") or item.get("phone")
            website = item.get("website")
            address = item.get("address") or item.get("streetAddress") or item.get("fullAddress")
            # Filtrado estricto: asegurar que los resultados pertenezcan exactamente al código postal y país seleccionados
            addr_l = (address or "").lower()
            postal_ok = False
            
            # Validación estricta por código postal
            if postal_code and address:
                # Buscar el código postal como palabra completa, no como substring
                import re
                # Para España: buscar el código postal exacto (5 dígitos)
                if country == 'ES':
                    postal_pattern = rf'\b{re.escape(postal_code)}\b'
                    if re.search(postal_pattern, addr_l):
                        postal_ok = True
                else:
                    # Para otros países: buscar el código postal exacto considerando formatos con espacios/guiones
                    postal_clean = postal_code.replace(' ', '').replace('-', '')
                    addr_clean = addr_l.replace(' ', '').replace('-', '')
                    if postal_clean in addr_clean:
                        # Verificación adicional: buscar el código postal como palabra completa
                        postal_pattern = rf'\b{re.escape(postal_code)}\b'
                        if re.search(postal_pattern, addr_l):
                            postal_ok = True
            
            # Validación estricta por país
            country_ok = False
            if postal_ok:
                # Verificar que el resultado pertenece al país correcto
                country_field = (item.get('country') or '').strip()
                
                # 1. Verificar campo 'country' directo de la API
                if country_field:
                    if country_field.upper() == country.upper():
                        country_ok = True
                
                # 2. Si no hay campo country o no coincide, verificar por patrones en la dirección
                if not country_ok:
                    if country == 'ES':
                        # Para España: buscar indicadores específicos
                        spain_indicators = ['españa', 'spain', 'es ', ', es', 'madrid', 'barcelona', 'valencia', 'sevilla', 'zaragoza']
                        if any(indicator in addr_l for indicator in spain_indicators):
                            country_ok = True
                    elif country == 'FR':
                        # Para Francia: buscar indicadores específicos
                        france_indicators = ['france', 'francia', 'fr ', ', fr', 'paris', 'lyon', 'marseille']
                        if any(indicator in addr_l for indicator in france_indicators):
                            country_ok = True
                    elif country == 'DE':
                        # Para Alemania: buscar indicadores específicos
                        germany_indicators = ['germany', 'alemania', 'deutschland', 'de ', ', de', 'berlin', 'munich', 'hamburg']
                        if any(indicator in addr_l for indicator in germany_indicators):
                            country_ok = True
                    elif country == 'IT':
                        # Para Italia: buscar indicadores específicos
                        italy_indicators = ['italy', 'italia', 'it ', ', it', 'roma', 'milano', 'napoli']
                        if any(indicator in addr_l for indicator in italy_indicators):
                            country_ok = True
                    elif country == 'BE':
                        # Para Bélgica: buscar indicadores específicos
                        belgium_indicators = ['belgium', 'bélgica', 'belgique', 'be ', ', be', 'brussels', 'bruxelles', 'antwerp']
                        if any(indicator in addr_l for indicator in belgium_indicators):
                            country_ok = True
                    elif country == 'PT':
                        # Para Portugal: buscar indicadores específicos
                        portugal_indicators = ['portugal', 'pt ', ', pt', 'lisboa', 'porto', 'coimbra']
                        if any(indicator in addr_l for indicator in portugal_indicators):
                            country_ok = True
                    else:
                        # Para otros países: verificación genérica
                        if country.lower() in addr_l or gl in addr_l:
                            country_ok = True
            
            # Para buscar aún más, cuando no hay coincidencia estricta por CP,
            # aceptar coincidencia por nombre de ciudad en la dirección como fallback adicional.
            # Mantener filtro por país para evitar ruido transfronterizo.
            if not (postal_ok and country_ok):
                city_in_addr = False
                if address and country_ok:
                    # Intentar extraer ciudad de la consulta cuando el usuario la aportó
                    # (no disponible en este método; solo activar fallback si la dirección contiene el CP
                    # o si la API indica localidad/ciudad en campos secundarios)
                    locality = (item.get('locality') or item.get('city') or item.get('suburb') or '').strip()
                    if locality and _norm(locality) in addr_l:
                        city_in_addr = True
                if not city_in_addr:
                    continue
                continue
            
            # Deduplicación más inteligente para evitar perder resultados válidos
            name_clean = (name or '').strip().lower()
            address_clean = (address or '').strip().lower()
            phone_clean = (phone or '').strip().lower()
            website_clean = (website or '').strip().lower()
            
            # Crear múltiples claves de deduplicación para mayor precisión
            dedup_keys = [
                f"{name_clean}|{address_clean}",  # Clave principal: nombre + dirección
                f"{name_clean}|{phone_clean}" if phone_clean and phone_clean != "-" else None,  # nombre + teléfono
                f"{address_clean}|{phone_clean}" if phone_clean and phone_clean != "-" else None,  # dirección + teléfono
            ]
            
            # Verificar si ya existe alguna combinación
            is_duplicate = False
            for key in dedup_keys:
                if key and key in seen_keys:
                    is_duplicate = True
                    break
            
            if is_duplicate:
                continue
                
            # Agregar todas las claves válidas al conjunto
            for key in dedup_keys:
                if key:
                    seen_keys.add(key)
            # Intentar obtener email desde la web si hay sitio
            email_value: str | None = None
            try:
                if website:
                    # Normalizar y cachear
                    w = website.strip()
                    cached = email_cache.get(w)
                    if cached is None:
                        cached = fetch_email_from_website(w)
                        email_cache[w] = cached
                    email_value = cached
            except Exception:
                email_value = None

            aggregated.append({
                "name": name or "-",
                "phone": phone or "-",
                "email": (email_value or "-"),
                "address": address or (website or "-"),
            })
            # No cortar aquí - permitir que se procesen todos los modificadores
        # Solo verificar límite entre diferentes modificadores para mejor distribución
        if len(aggregated) >= limit:
            break

    if not aggregated:
        return {}

    return {"Resultados": aggregated[:limit]}


def scrape_businesses_by_city_and_category(city: str, category: str, postal_code: str | None = None, limit: int = 20, api_key: str | None = None, country: str = 'ES'):
    """Scraping por ciudad obligatoria y CP opcional usando Serper (Google Local).
    Si se proporciona `postal_code`, se usa para afinar y filtrar resultados; si no,
    se busca por ciudad completa.
    """
    if not api_key:
        raise RuntimeError("Falta SERPER_API_KEY en settings")

    url = "https://google.serper.dev/places"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    aggregated: list[dict] = []
    seen_keys = set()
    # Incrementar tamaño por lote para recoger más resultados
    per_batch = min(100, max(25, limit // 3))

    base_modifiers = [
        "",
        # Variaciones geográficas y sinónimos frecuentes
        "centro", "norte", "sur", "este", "oeste",
        "cerca", "próximo", "local", "zona", "cercano", "alrededor",
        # Términos comerciales y sinónimos
        "tienda", "negocio", "empresa", "comercio", "establecimiento",
        # Términos de servicio y profesionales
        "servicio", "profesional", "especialista", "proveedor",
        # Formatos alternativos al CP, por si la fuente responde mejor a "código postal" explícito
        "codigo postal", "cp",
    ]

    country_specific = []
    if country == 'ES':
        country_specific = [
            "barrio", "distrito", "municipio", "localidad", "pueblo",
            "provincia", "comunidad", "area metropolitana"
        ]
        country_name = "España"
    elif country == 'FR':
        country_specific = ["quartier", "arrondissement", "commune", "ville"]
        country_name = "France"
    elif country == 'DE':
        country_specific = ["stadtteil", "bezirk", "gemeinde", "stadt"]
        country_name = "Germany"
    elif country == 'IT':
        country_specific = ["quartiere", "zona", "comune", "città"]
        country_name = "Italy"
    elif country == 'BE':
        country_specific = ["wijk", "gemeente", "stad", "commune"]
        country_name = "Belgium"
    elif country == 'PT':
        country_specific = ["bairro", "freguesia", "concelho", "cidade"]
        country_name = "Portugal"
    else:
        country_name = country

    query_modifiers = base_modifiers + country_specific

    email_cache: dict[str, str | None] = {}

    gl = (country or 'ES').lower()
    hl = 'es' if gl == 'es' else 'en'

    for mod in query_modifiers:
        if mod == "":
            q = f"{category} {city} {country_name}".strip()
        elif mod in ["centro", "norte", "sur", "este", "oeste"]:
            q = f"{category} {city} {mod} {country_name}".strip()
        elif mod in ["cerca", "próximo", "local", "zona", "cercano", "alrededor"]:
            q = f"{category} {mod} {city} {country_name}".strip()
        elif mod in ["tienda", "negocio", "empresa", "comercio", "establecimiento"]:
            q = f"{mod} {category} {city} {country_name}".strip()
        elif mod in ["servicio", "profesional", "especialista", "proveedor"]:
            q = f"{category} {mod} {city} {country_name}".strip()
        else:
            q = f"{category} {mod} {city} {country_name}".strip()

        # Incluir CP en la consulta si se proporcionó para afinar
        if postal_code:
            q = f"{q} {postal_code}".strip()

        payload = {"q": q, "gl": gl, "hl": hl, "num": per_batch}

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=45)
                if r.status_code == 401:
                    raise RuntimeError("API key de Serper inválida o sin permisos")
                if r.status_code == 404:
                    break
                if r.status_code == 429:
                    if attempt < max_retries:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        break
                r.raise_for_status()
                data = r.json()
                results = data.get("places") or data.get("localResults") or data.get("placeResults") or []
                break
            except Exception:
                if attempt < max_retries:
                    continue
                else:
                    results = []
                    break

        for item in results:
            name = item.get("title") or item.get("name")
            phone = item.get("phoneNumber") or item.get("phone")
            website = item.get("website")
            address = item.get("address") or item.get("streetAddress") or item.get("fullAddress")

            # Normalizar acentos para matching robusto de ciudad/pueblo
            import unicodedata
            def _norm(s):
                try:
                    return ''.join(c for c in unicodedata.normalize('NFD', (s or '').lower()) if unicodedata.category(c) != 'Mn')
                except Exception:
                    return (s or '').lower()

            addr_l = _norm(address)
            city_norm = _norm(city)

            # Considerar múltiples campos de localidad que puede devolver Serper
            locality_fields = [
                (item.get('locality') or ''),
                (item.get('city') or ''),
                (item.get('suburb') or ''),
                (item.get('municipality') or ''),
                (item.get('region') or ''),
            ]
            locality_norms = [_norm(x) for x in locality_fields if x]

            city_ok = (city_norm in addr_l) or any(city_norm in ln for ln in locality_norms)

            # Si se especificó CP, también verificarlo
            postal_ok = True
            if postal_code:
                postal_ok = False
                if address:
                    import re
                    if country == 'ES':
                        postal_pattern = rf"\b{re.escape(postal_code)}\b"
                        if re.search(postal_pattern, addr_l):
                            postal_ok = True
                    else:
                        postal_clean = postal_code.replace(' ', '').replace('-', '')
                        addr_clean = addr_l.replace(' ', '').replace('-', '')
                        if postal_clean in addr_clean:
                            postal_pattern = rf"\b{re.escape(postal_code)}\b"
                            if re.search(postal_pattern, addr_l):
                                postal_ok = True

            if not (city_ok and postal_ok):
                continue

            # Deduplicación por nombre+dirección/teléfono
            name_clean = (name or '').strip().lower()
            address_clean = (address or '').strip().lower()
            phone_clean = (phone or '').strip().lower()
            website_clean = (website or '').strip().lower()
            keys = [
                f"{name_clean}|{address_clean}",
                f"{name_clean}|{phone_clean}" if phone_clean and phone_clean != '-' else None,
                f"{address_clean}|{phone_clean}" if phone_clean and phone_clean != '-' else None,
            ]
            if any(k and k in seen_keys for k in keys):
                continue
            for k in keys:
                if k:
                    seen_keys.add(k)

            email_value: str | None = None
            try:
                if website:
                    w = website.strip()
                    cached = email_cache.get(w)
                    if cached is None:
                        cached = fetch_email_from_website(w)
                        email_cache[w] = cached
                    email_value = cached
            except Exception:
                email_value = None

            aggregated.append({
                "name": name or "-",
                "phone": phone or "-",
                "email": (email_value or "-"),
                "address": address or (website or "-"),
            })

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


@require_POST
@login_required
def filter_excel_by_cp_view(request):
    """Ejemplo POST view que filtra un Excel por código postal español.

    Parámetros esperados (JSON o multipart/form-data):
    - file: (opcional) archivo Excel subido. Si no se proporciona, se puede enviar
      `filename` con una ruta relativa en MEDIA_ROOT/exports.
    - postal_code: código postal objetivo (5 dígitos). Si se omite, devuelve
      todas las filas que contengan cualquier CP español válido.

    Responde JSON con conteo y ruta del archivo exportado si hay resultados.
    """
    # Soportar multipart/form-data (file upload) o JSON
    postal_raw = request.POST.get('postal_code') or (json.loads(request.body.decode('utf-8')).get('postal_code') if request.content_type == 'application/json' and request.body else None)
    postal_code = None
    if postal_raw:
        postal_code = ''.join(ch for ch in str(postal_raw) if ch.isdigit())[:5]
        if postal_code and not re.fullmatch(r"\d{5}", postal_code):
            return HttpResponseBadRequest("postal_code debe tener 5 dígitos")

    # Obtener archivo: preferir upload
    uploaded = request.FILES.get('file')
    filename = request.POST.get('filename')

    try:
        import pandas as pd
    except Exception:
        return HttpResponseBadRequest('pandas es requerido en el servidor para procesar Excel')

    if uploaded:
        # Leer directamente desde el archivo subido
        try:
            df = pd.read_excel(uploaded)
        except Exception as e:
            return HttpResponseBadRequest(f'Error leyendo Excel subido: {e}')
    elif filename:
        # Construir ruta dentro de MEDIA_ROOT/exports por seguridad
        path = os.path.join(settings.MEDIA_ROOT, 'exports', os.path.basename(filename))
        if not os.path.exists(path):
            return HttpResponseBadRequest('Archivo no encontrado en exports')
        try:
            df = pd.read_excel(path)
        except Exception as e:
            return HttpResponseBadRequest(f'Error leyendo Excel: {e}')
    else:
        return HttpResponseBadRequest('Proporciona un archivo subido o filename')

    # Normalizar nombres de columna esperados
    # El util espera columna 'direccion' por defecto
    # Hacemos una copia y renombramos si detectamos 'Dirección' u otras variantes
    df_columns_lower = {c.lower(): c for c in df.columns}
    if 'direccion' not in df_columns_lower:
        # intentar variantes en español/inglés
        for candidate in ('dirección', 'address', 'direcciones'):
            if candidate in df_columns_lower:
                df = df.rename(columns={df_columns_lower[candidate]: 'direccion'})
                break

    try:
        filtered = postal_utils.filter_dataframe_by_spanish_cp(df, postal_code=postal_code, addr_col='direccion')
    except Exception as e:
        return HttpResponseBadRequest(f'Error filtrando datos: {e}')

    if filtered.empty:
        return JsonResponse({'results': 0, 'message': 'No se encontraron filas que cumplan los criterios'})

    # Exportar resultado a Excel
    out_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
    os.makedirs(out_dir, exist_ok=True)
    out_name = f'filtered_{uuid.uuid4().hex}.xlsx'
    out_path = os.path.join(out_dir, out_name)
    try:
        filtered.to_excel(out_path, index=False)
    except Exception as e:
        return HttpResponseBadRequest(f'Error exportando Excel: {e}')

    return JsonResponse({'results': len(filtered), 'download': f'/media/exports/{out_name}'})
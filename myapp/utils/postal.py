"""Utilities para extraer y validar códigos postales españoles desde texto.

Funciones principales:
- is_spanish_cp(cp_str): valida si una cadena de 5 dígitos corresponde a un CP español (01000-52999).
- extract_spanish_postal_codes_from_text(text): devuelve lista de códigos postales españoles encontrados en el texto.
- filter_dataframe_by_spanal_cp(df, postal_code=None, addr_col='direccion'):
    filtra un DataFrame (pandas) para mantener solo filas cuya columna de dirección contiene
    un código postal español. Si `postal_code` se pasa como string de 5 dígitos, se
    filtran además las filas que contienen exactamente ese CP.

El módulo evita falsos positivos comunes (por ejemplo, códigos franceses 5 dígitos que no
empiezan por prefijo español) mediante la validación del rango.
"""
from __future__ import annotations

import re
from typing import List, Optional


CP_RE = re.compile(r"\b(\d{5})\b")


def is_spanish_cp(cp_str: str) -> bool:
    """Valida si cp_str (debe ser 5 dígitos) es un código postal español.

    Reglas aplicadas:
    - Debe tener exactamente 5 dígitos
    - El valor numérico debe estar entre 01000 y 52999 incl.
      (esto cubre prefijos provinciales 01-52 y espacios postales válidos)
    """
    if not isinstance(cp_str, str):
        return False
    if not re.fullmatch(r"\d{5}", cp_str):
        return False
    try:
        val = int(cp_str)
    except ValueError:
        return False
    # Rango: desde 01000 (1000) hasta 52999
    if val < 1000:
        # ej. '00001' no válido
        return False
    if val < 10000:
        # valores <10000 corresponden a CP con ceros iniciales posible, por ejemplo '01001'
        # pero int('01001')=1001; permitimos >=1000
        pass
    return 1000 <= val <= 52999


def extract_spanish_postal_codes_from_text(text: str) -> List[str]:
    """Extrae todos los tokens de 5 dígitos del texto y devuelve solo los que
    son códigos postales españoles válidos (usando is_spanish_cp).

    Devuelve una lista de cadenas únicas en el orden de aparición.
    """
    if not text:
        return []
    found = CP_RE.findall(str(text))
    seen = set()
    out: List[str] = []
    for cp in found:
        if cp in seen:
            continue
        if is_spanish_cp(cp):
            seen.add(cp)
            out.append(cp)
    return out


def filter_dataframe_by_spanish_cp(df, postal_code: Optional[str] = None, addr_col: str = 'direccion'):
    """Filtra un DataFrame pandas `df` y devuelve uno nuevo con estas reglas:

    - Mantiene solo filas donde la columna `addr_col` contenga al menos un código postal
      español válido según `is_spanish_cp`.
    - Si `postal_code` es una cadena de 5 dígitos, devuelve solo filas que contienen
      exactamente ese código postal en la dirección.

    Notas:
    - No hacemos lectura/escritura de Excel aquí; el caller debe cargar el Excel con pandas.
    - La comparación de `postal_code` es textual (se busca la subcadena exacta sobre
      la columna de dirección) y se normaliza a dígitos.

    Retorna el DataFrame filtrado (nueva vista). Requiere pandas.
    """
    try:
        import pandas as pd
    except Exception as e:
        raise RuntimeError("pandas es requerido para usar filter_dataframe_by_spanish_cp") from e

    if addr_col not in df.columns:
        raise KeyError(f"Columna de dirección '{addr_col}' no encontrada en el DataFrame")

    # Normalizar postal_code si se proporciona
    postal_code_digits: Optional[str] = None
    if postal_code:
        postal_code_digits = ''.join(ch for ch in str(postal_code) if ch.isdigit())
        if not re.fullmatch(r"\d{5}", postal_code_digits or ""):
            raise ValueError("postal_code debe ser 5 dígitos si se especifica")

    def row_has_spanish_cp(addr: str) -> bool:
        if not isinstance(addr, str):
            return False
        # Buscamos tokens de 5 dígitos y validamos cada uno
        for cp in CP_RE.findall(addr):
            if is_spanish_cp(cp):
                if postal_code_digits:
                    if cp == postal_code_digits:
                        return True
                else:
                    return True
        return False

    mask = df[addr_col].apply(row_has_spanish_cp)
    return df[mask].copy()


if __name__ == '__main__':
    # Pequeño demo si se ejecuta directamente (útil para pruebas rápidas)
    import pandas as pd

    sample = pd.DataFrame({
        'direccion': [
            'Calle Mayor 1, 28001 Madrid, España',
            '10 Rue de la Paix, 75002 Paris, France',
            'Av. de Andalucía, 41012 Sevilla',
            'Some place 12345 Somewhere',
            'C/ Falsa 123, 01005 Vitoria-Gasteiz'
        ],
        'telefono': ['111', '222', '333', '444', '555'],
        'email': ['a@a.com', 'b@b.fr', 'c@c.es', '-', 'd@d.es'],
        'nombre': ['A', 'B', 'C', 'D', 'E']
    })
    print('Todos los CP encontrados:')
    print(sample['direccion'].apply(extract_spanish_postal_codes_from_text))
    print('\nFiltrado (solo españoles):')
    print(filter_dataframe_by_spanish_cp(sample))
    print('\nFiltrado con postal_code=28001:')
    print(filter_dataframe_by_spanish_cp(sample, postal_code='28001'))

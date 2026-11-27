"""Exporta una fotografía pública y completa del catálogo para el sitio visual."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from historico import _amount, effective_price


ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'estado.json'
OUTPUT = ROOT / 'catalogo.json'
SITE = 'https://sidecompras.com.ar'


def _argentina_now():
    try:
        return datetime.now(ZoneInfo('America/Argentina/Buenos_Aires'))
    except ZoneInfoNotFoundError:
        # En Windows puede no estar instalada la base de zonas horarias.
        return datetime.now(timezone(timedelta(hours=-3)))


def _previous_detections():
    if not OUTPUT.exists():
        return {}
    data = json.loads(OUTPUT.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('productos'), list):
        raise ValueError('Catálogo exportado anterior inválido')
    return {p['codigo']: p.get('primera_deteccion') for p in data['productos']
            if isinstance(p, dict) and isinstance(p.get('codigo'), str)}


def _seen():
    if not STATE.exists():
        return None
    data = json.loads(STATE.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('vistos'), list):
        raise ValueError('Estado anterior de productos inválido')
    return set(data['vistos'])


def _text(value):
    return value if isinstance(value, str) else ''


def run(current):
    """Guarda el catálogo completo. Llamar antes de actualizar estado.json."""
    if not isinstance(current, dict) or not current:
        raise ValueError('No se exporta un catálogo vacío o inválido')
    now = _argentina_now()
    timestamp = now.isoformat(timespec='seconds')
    previous = _previous_detections()
    seen = _seen()
    products = []
    for code, item in current.items():
        if not isinstance(code, str) or not code or item.get('codigo') != code:
            raise ValueError('Producto sin código válido')
        first = previous.get(code)
        if first is None and seen is not None and code not in seen:
            first = timestamp
        photo = _text(item.get('foto'))
        photo = SITE + photo if photo.startswith('/fotos/') else ''
        products.append({
            'codigo': code,
            'titulo': _text(item.get('titulo')),
            'rubro': _text(item.get('rubro')),
            'comercio': _text(item.get('comercio')),
            'comercio_codigo': item.get('comercio_codigo'),
            'localidad': _text(item.get('localidad')),
            'foto': photo,
            'url': SITE + '/#/producto/' + quote(code, safe=''),
            # Centavos enteros permiten representar precios sin redondeo binario.
            'precio_centavos': _amount(item.get('precio')),
            'precio_vigente_centavos': effective_price(item),
            'descuento': _text(item.get('descuento')),
            'reintegro': item.get('reintegro') is True,
            'promo': _text(item.get('promo')),
            'stock_publicado': item.get('stock'),
            'vendidos': item.get('vendidos'),
            'destacado': item.get('destacado') is True,
            'puntaje': item.get('puntaje'),
            'opiniones': item.get('opiniones'),
            'nuevo_tienda': item.get('nuevo') is True,
            'primera_deteccion': first,
        })
    data = {'version': 1, 'actualizado': timestamp, 'total': len(products), 'productos': products}
    temp = OUTPUT.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
        os.replace(temp, OUTPUT)
    finally:
        temp.unlink(missing_ok=True)
    print(f'Catálogo visual exportado: {len(products)} productos.', flush=True)

"""Muestra pública y acotada de catálogos VTEX; no identifica ubicación del cliente."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import time
import exportar_xtr
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'supermercados.json'
STORES = ({'id': 'vea', 'nombre': 'Vea', 'host': 'www.vea.com.ar'},
          {'id': 'mas', 'nombre': 'Más Online', 'host': 'www.masonline.com.ar'})
RANGE = re.compile(r'^(\d+)-(\d+)/(\d+)$')


def now():
    try:
        tz = ZoneInfo('America/Argentina/Buenos_Aires')
    except ZoneInfoNotFoundError:
        tz = timezone(timedelta(hours=-3))
    return datetime.now(tz).isoformat(timespec='seconds')


def cents(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value)) * 100
        return int(amount) if amount.is_finite() and amount > 0 and amount == amount.to_integral_value() else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def url(value, host=None):
    if not isinstance(value, str):
        return ''
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or (host and parts.hostname != host):
        return ''
    return value


def fetch_page(store, start, size):
    endpoint = f"https://{store['host']}/api/catalog_system/pub/products/search?_from={start}&_to={start + size - 1}"
    req = Request(endpoint, headers={'User-Agent': 'SideCatalogo/1.0', 'Accept': 'application/json'})
    with urlopen(req, timeout=30) as response:
        resource = response.headers.get('resources', '')
        data = json.load(response, parse_float=Decimal)
    return resource, data


def installments(offer, price):
    """Sólo cuotas explícitamente sin interés y coherentes con el precio vigente."""
    if not price:
        return []
    payment_options = offer.get('PaymentOptions') or {}
    if not isinstance(payment_options, dict):
        return []
    choices = payment_options.get('installmentOptions') or []
    if not isinstance(choices, list):
        return []
    best = {}
    for option in choices:
        if not isinstance(option, dict) or option.get('paymentGroupName') != 'creditCardPaymentGroup' or option.get('bin'):
            continue
        medium = option.get('paymentName')
        plans = option.get('installments')
        if not isinstance(medium, str) or not medium.strip() or not isinstance(plans, list):
            continue
        medium = medium.strip()[:80]
        for plan in plans:
            if not isinstance(plan, dict):
                continue
            count, value, total = plan.get('count'), plan.get('value'), plan.get('total')
            rate = plan.get('interestRate')
            if (plan.get('hasInterestRate') is not False or isinstance(rate, bool)
                    or not isinstance(rate, (int, float, Decimal)) or rate != 0
                    or type(count) is not int or not 2 <= count <= 36
                    or type(value) is not int or value <= 0
                    or type(total) is not int or total != price or abs(value * count - total) > count):
                continue
            candidate = {'tipo': 'cuotas', 'medio': medium, 'cantidad_cuotas': count,
                         'monto_cuota_centavos': value, 'total_centavos': total, 'sin_interes': True,
                         'condiciones': 'Según datos publicados por la tienda; sujeto a tarjeta, ubicación y confirmación en checkout.'}
            if medium not in best or count > best[medium]['cantidad_cuotas']:
                best[medium] = candidate
    return list(best.values())[:15]


def variants(store, product):
    pid = str(product.get('productId') or '')
    name = product.get('productName') or ''
    categories = product.get('categories') or []
    category = str(categories[0]).strip('/').replace('/', ' / ') if categories else ''
    results = []
    for item in product.get('items') or []:
        sku = str(item.get('itemId') or '')
        if not sku:
            continue
        sellers = item.get('sellers') or []
        seller = next((s for s in sellers if s.get('sellerDefault')), sellers[0] if sellers else {})
        offer = seller.get('commertialOffer') or {}
        available = bool(offer.get('AvailableQuantity', 0) > 0)
        price = cents(offer.get('Price')) if available else None
        listed = cents(offer.get('ListPrice')) if available else None
        photos = item.get('images') or []
        photo = url(photos[0].get('imageUrl')) if photos and isinstance(photos[0], dict) else ''
        results.append({'codigo': f"vtex:{store['id']}:{sku}", 'titulo': str(name),
                        'rubro': category, 'comercio': store['nombre'], 'localidad': '',
                        'foto': photo, 'url': url(product.get('link'), store['host']),
                        'precio_centavos': listed or price, 'precio_vigente_centavos': price,
                        'ean': str(item.get('ean') or ''), 'sku': sku, 'producto_id': pid,
                        'disponible': available, 'promociones': installments(offer, price)})
    return results


def collect(store, max_pages=10, page_size=50, delay=0.4):
    report = {'id': store['id'], 'nombre': store['nombre'], 'actualizado': now(),
              'cobertura': {'total_publicado': None, 'productos_consultados': 0,
                            'skus_exportados': 0, 'paginas': 0, 'completa': False, 'limitada': False},
              'error': None, 'advertencia': None, 'productos': []}
    coverage = report['cobertura']
    seen_products, seen_skus = set(), set()
    try:
        for page in range(max_pages):
            if page:
                time.sleep(delay)
            start = page * page_size
            resource, data = fetch_page(store, start, page_size)
            match = RANGE.fullmatch(resource)
            if not isinstance(data, list) or not match:
                raise ValueError('Página o encabezado resources inválidos; cobertura no verificable')
            first, last, total = map(int, match.groups())
            if first != start or last < first or last >= total or last - first + 1 != len(data):
                raise ValueError('Rango de productos inconsistente')
            if coverage['total_publicado'] is None:
                coverage['total_publicado'] = total
            elif total != coverage['total_publicado']:
                difference = abs(total - coverage['total_publicado'])
                if difference > max(20, coverage['total_publicado'] // 1000):
                    raise ValueError('El total de resultados cambió considerablemente durante la consulta')
                report['advertencia'] = 'El total publicado varió durante la consulta; la cobertura es aproximada.'
            for product in data:
                pid = str(product.get('productId') or '') if isinstance(product, dict) else ''
                if not pid or pid in seen_products:
                    raise ValueError('Producto sin identificación o repetido entre páginas')
                seen_products.add(pid)
                for variant in variants(store, product):
                    if variant['codigo'] in seen_skus:
                        raise ValueError('SKU repetido en el catálogo')
                    seen_skus.add(variant['codigo'])
                    report['productos'].append(variant)
            coverage['paginas'] += 1
            coverage['productos_consultados'] = len(seen_products)
            coverage['skus_exportados'] = len(report['productos'])
            if last + 1 == total:
                coverage['completa'] = len(seen_products) == total and not report['advertencia']
                break
            if len(data) != page_size:
                raise ValueError('Página incompleta antes del final del catálogo')
        if not coverage['completa']:
            coverage['limitada'] = coverage['paginas'] == max_pages
    except Exception as exc:
        report['error'] = str(exc)[:300] or type(exc).__name__
        coverage['productos_consultados'] = len(seen_products)
        coverage['skus_exportados'] = len(report['productos'])
    return report


def run(max_pages=10, page_size=50, delay=0.4, output=OUTPUT):
    if not (1 <= max_pages <= 100 and 1 <= page_size <= 50 and delay >= 0.4):
        raise ValueError('Límites: 1–100 páginas, 1–50 productos por página y pausa mínima de 0,4 segundos')
    output = Path(output)
    previous = {}
    if output.exists():
        try:
            prior = json.loads(output.read_text(encoding='utf-8'))
            if prior.get('version') == 1 and isinstance(prior.get('tiendas'), list):
                previous = {s['id']: s for s in prior['tiendas'] if isinstance(s, dict) and s.get('id')}
        except (ValueError, OSError, AttributeError):
            pass
    stores = [collect(store, max_pages, page_size, delay) for store in STORES]
    stores.append(exportar_xtr.collect(max_pages=min(max_pages, 30), delay=delay))
    for index, store in enumerate(stores):
        old = previous.get(store['id'])
        if store['error'] and not store['productos'] and isinstance(old, dict) and old.get('productos'):
            kept = dict(old)
            kept['intento_actualizado'] = store['actualizado']
            kept['error'] = store['error']
            kept['advertencia'] = 'Falló la actualización; se conserva la muestra anterior.'
            stores[index] = kept
    result = {'version': 1, 'actualizado': now(), 'tiendas': stores}
    temp = output.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    # La comparación se recalcula incluso si una tienda falló: nunca se publican
    # como actuales referencias conservadas de una lectura anterior.
    import comparar_supermercados
    comparar_supermercados.write(result, output=output.with_name('comparaciones.json'))
    for store in stores:
        c = store['cobertura']
        print(f"{store['nombre']}: {c['productos_consultados']}/{c['total_publicado']} productos; error: {store['error'] or 'ninguno'}", flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paginas', type=int, default=10)
    parser.add_argument('--pausa', type=float, default=0.4)
    args = parser.parse_args()
    run(max_pages=args.paginas, delay=args.pausa)

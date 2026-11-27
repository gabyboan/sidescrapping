"""Lectura acotada del listado público de XTR; no afirma cubrir toda la tienda."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.reading = False
        self.text = []
        self.products = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type', '').lower() == 'application/ld+json':
            self.reading = True
            self.text = []

    def handle_data(self, data):
        if self.reading:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag != 'script' or not self.reading:
            return
        self.reading = False
        try:
            data = json.loads(''.join(self.text))
        except (TypeError, ValueError):
            return
        if isinstance(data, dict) and data.get('@type') == 'Product':
            self.products.append(data)


def _https(value, host=None):
    if not isinstance(value, str):
        return ''
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or (host and parsed.hostname != host):
        return ''
    return value


def _cents(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value)) * 100
        if amount.is_finite() and amount > 0 and amount == amount.to_integral_value():
            return int(amount)
    except (InvalidOperation, ValueError, OverflowError):
        pass
    return None


def _product(data):
    offer = data.get('offers')
    if not isinstance(offer, dict) or offer.get('priceCurrency') != 'ARS':
        raise ValueError('Oferta de XTR sin precio en pesos verificable')
    sku = str(data.get('sku') or '').strip()
    title = str(data.get('name') or '').strip()
    target = _https(offer.get('url'), 'www.xtr.com.ar')
    if not sku or not title or not target:
        raise ValueError('Producto de XTR sin identificación o enlace verificable')
    available = offer.get('availability') == 'https://schema.org/InStock'
    price = _cents(offer.get('price')) if available else None
    photo = data.get('image')
    if isinstance(photo, list):
        photo = photo[0] if photo else ''
    # JSON-LD publica el precio de la oferta, no el precio tachado. No se
    # descuentan promociones de transferencia, cuotas ni beneficios bancarios.
    return {'codigo': f'xtr:{sku}', 'titulo': title, 'rubro': 'Tecnología',
            'comercio': 'XTR', 'localidad': '', 'foto': _https(photo), 'url': target,
            'precio_centavos': price, 'precio_vigente_centavos': price,
            'ean': str(data.get('gtin13') or data.get('gtin') or ''), 'sku': sku,
            'producto_id': sku, 'disponible': available}


def collect(max_pages=10, delay=0.4):
    """Consultar hasta diez páginas por defecto; el total real no está verificado."""
    if not (1 <= max_pages <= 30 and delay >= 0.4):
        raise ValueError('Límites XTR: 1–30 páginas y pausa mínima de 0,4 segundos')
    now = datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec='seconds')
    report = {'id': 'xtr', 'nombre': 'XTR', 'actualizado': now,
              'cobertura': {'total_publicado': None, 'productos_consultados': 0,
                            'skus_exportados': 0, 'paginas': 0, 'completa': False,
                            'limitada': True}, 'error': None, 'productos': []}
    seen, page_fingerprints = set(), set()
    try:
        for page in range(1, max_pages + 1):
            if page > 1:
                time.sleep(delay)
            req = Request(f'https://www.xtr.com.ar/productos/?page={page}',
                          headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html'})
            with urlopen(req, timeout=30) as response:
                html = response.read(4_000_001)
            if len(html) > 4_000_000:
                raise ValueError('Página de XTR demasiado grande')
            parser = ProductParser()
            parser.feed(html.decode('utf-8', errors='replace'))
            items = [_product(data) for data in parser.products]
            if not items:
                raise ValueError('XTR no devolvió productos verificables en la página')
            fingerprint = tuple(x['codigo'] for x in items)
            if fingerprint in page_fingerprints:
                raise ValueError('XTR repitió una página; no se pudo verificar el fin del catálogo')
            page_fingerprints.add(fingerprint)
            for item in items:
                if item['codigo'] not in seen:
                    seen.add(item['codigo'])
                    report['productos'].append(item)
            report['cobertura']['paginas'] += 1
            report['cobertura']['productos_consultados'] = len(seen)
            report['cobertura']['skus_exportados'] = len(report['productos'])
    except Exception as exc:
        report['error'] = str(exc)[:300] or type(exc).__name__
    return report

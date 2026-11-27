from urllib.request import urlopen
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlsplit, unquote
import hashlib
import json
import os
import re

from monitor import clean, get_json

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'ofertas_estado.json'
LIST = ROOT / 'OFERTAS.md'
COMPARISONS = ROOT / 'comparaciones_side.json'
MARKET_OUTPUT = ROOT / 'mercado.json'
SOURCE = 'https://soloprecio.com.ar/data/comparador/celulares.json'
WATCH = {
    '22487-YB2EES': {'sku': 'phone_samsung_s26ultra_256gb_5g', 'ram': 12, 'capacity': 256},
    '22489-PERMWQ': {'sku': 'phone_samsung_a17_128gb_4gbram', 'ram': 4, 'capacity': 128},
    '22489-4S7VTY': {'sku': 'phone_samsung_a36_256gb_5g', 'ram': 8, 'capacity': 256},
    '22487-QABC42': {'sku': 'phone_motorola_motog15_128gb_4gbram', 'ram': 4, 'capacity': 128},
    '22487-J6KYC2': {'sku': 'phone_motorola_motog17_128gb_4gbram', 'ram': 4, 'capacity': 128},
}
MARKER = re.compile(r'<!-- sidecompras-oferta:([0-9a-f]{20}) -->')


def verified_offers(product, ram, capacity, model, network=None, now=None):
    """Oferta independiente: modelo, capacidad, RAM, stock y fecha comprobables.

    SoloPrecio publica importes argentinos en pesos; si incorpora un campo de
    moneda, se rechaza cualquier moneda distinta de ARS.
    """
    now = now or datetime.now(timezone(timedelta(hours=-3)))
    result = {}
    for offer in product.get('offers', []):
        try:
            if offer.get('inStock') is not True or offer.get('trusted') is not True:
                continue
            if offer.get('currency', 'ARS').upper() != 'ARS' or offer.get('ram') != ram:
                continue
            if offer.get('condicion') and str(offer['condicion']).lower() not in ('nuevo', 'nueva'):
                continue
            url = offer['url']
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                continue
            path = unquote(parsed.path).lower()
            model_pattern = r'(?<![a-z0-9])(?:moto[-_ ]*|galaxy[-_ ]*)?' + r'[-_ ]*'.join(map(re.escape, model)) + r'(?![a-z0-9])'
            if not re.search(model_pattern, path):
                continue
            # El agrupador puede mezclar G17 y G17 Power, A56 y A56 Plus, etc.
            qualifiers = set(re.findall(r'(?<![a-z0-9])(ultra|plus|power|pro|lite|fusion|play|fe|neo|stylus)(?![a-z0-9])', path))
            if any(qualifier not in model for qualifier in qualifiers):
                continue
            capacities = {int(n) for n in re.findall(r'(?<![0-9])(64|128|256|512|1024)\s*[-_ ]?\s*(?:gb|giga)', path)}
            if capacities != {capacity}:
                continue
            networks = set(re.findall(r'(?<![a-z0-9])(4g|5g)(?![a-z0-9])', path))
            if networks and (not network or networks != {network}):
                continue
            captured = datetime.fromisoformat(offer['capturadoEn'])
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone(timedelta(hours=-3)))
            if not timedelta(0) <= now - captured <= timedelta(hours=48):
                continue
            price = Decimal(str(offer['price']))
            if not price.is_finite() or price <= 0 or price > 100_000_000:
                continue
            store = offer.get('store')
            if not isinstance(store, str) or not store.strip():
                continue
            entry = {'tienda': store.strip(), 'precio_centavos': int((price * 100).quantize(Decimal('1'))),
                     'url': url, 'observado': captured.isoformat(timespec='seconds')}
            key = store.strip().casefold()
            # Una sola observación por comercio, la de menor precio.
            if key not in result or entry['precio_centavos'] < result[key]['precio_centavos']:
                result[key] = entry
        except (KeyError, ValueError, TypeError, ArithmeticError, AttributeError):
            continue
    return sorted(result.values(), key=lambda item: item['precio_centavos'])


def model_config(product):
    # Los identificadores expresan una variante; las fichas genéricas/EAN
    # no bastan para reconstruir un modelo inequívoco desde enlaces.
    match = re.fullmatch(r'phone_(samsung|motorola)_(?:moto)?([a-z0-9]+)_(64|128|256|512|1024)gb(?:_(.*))?', str(product.get('id', '')))
    if not match:
        return None
    _, model, capacity, suffix = match.groups()
    suffix = suffix or ''
    if model in ('samsung', 'motorola') or len(model) < 2:
        return None
    # Si hay varias RAM, producir una comparación por configuración, nunca mezclarlas.
    network_match = re.search(r'(?:^|_)(4g|5g)(?:_|$)', suffix)
    name_network = re.search(r'\b(4g|5g)\b', str(product.get('name', '')).lower())
    if network_match and name_network and network_match.group(1) != name_network.group(1):
        return None
    return model, int(capacity), network_match.group(1) if network_match else (name_network.group(1) if name_network else None)


def export_market(catalog, now=None):
    now = now or datetime.now(timezone(timedelta(hours=-3)))
    products, comparisons = [], {}
    for product in catalog:
        config = model_config(product)
        if not config or product.get('inStock') is not True or product.get('isVerified') is not True:
            continue
        model, capacity, network = config
        for ram in sorted({o['ram'] for o in product.get('offers', []) if type(o.get('ram')) is int and 1 <= o['ram'] <= 32}):
            offers = verified_offers(product, ram, capacity, model, network, now)
            if len(offers) < 3:
                continue
            lowest, refs = offers[0], offers[1:]
            # Excluir la propia tienda del promedio y usar al menos dos comercios.
            average = int((Decimal(sum(r['precio_centavos'] for r in refs)) / len(refs)).quantize(Decimal('1')))
            if lowest['precio_centavos'] * 100 > average * 80:
                continue
            code = 'soloprecio:' + hashlib.sha256((product['id'] + ':' + str(ram)).encode()).hexdigest()[:20]
            observed = min((o['observado'] for o in offers), key=datetime.fromisoformat)
            products.append({'codigo': code, 'titulo': str(product.get('name') or product['id']) + f' · {ram} GB RAM / {capacity} GB',
                             'origen': lowest['tienda'], 'comercio': lowest['tienda'], 'rubro': 'Celulares',
                             'url': lowest['url'], 'foto': product.get('imageUrl') or '',
                             'precio_centavos': lowest['precio_centavos'], 'precio_vigente_centavos': lowest['precio_centavos'],
                             'disponible': True, 'observado_tienda': lowest['observado']})
            comparisons[code] = {'tipo': 'modelo', 'precio_centavos': lowest['precio_centavos'],
                'referencia_centavos': average, 'referencia_tienda': f'Promedio de {len(refs)} tiendas',
                'referencia_url': refs[0]['url'], 'ahorro_porcentaje': round((1 - lowest['precio_centavos'] / average) * 100, 1),
                'observado': observed, 'fuente': 'SoloPrecio', 'cantidad_referencias': len(refs), 'referencias': refs}
    return {'version': 1, 'actualizado': now.isoformat(timespec='seconds'), 'productos': products, 'comparaciones': comparisons}

def fetch_market():
    from urllib.request import Request
    request = Request(SOURCE, headers={'User-Agent': 'Mozilla/5.0 SidecomprasMonitor/1.0'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)['productos']

def market_price(config, catalog):
    try:
        zone = ZoneInfo('America/Argentina/Buenos_Aires')
    except Exception:
        zone = timezone(timedelta(hours=-3))
    now = datetime.now(zone).replace(tzinfo=None)
    matches = [p for p in catalog if p.get('id') == config['sku'] and p.get('inStock')]
    if len(matches) != 1:
        raise ValueError('No se encontró una ficha única y disponible')
    eligible = []
    for offer in matches[0].get('offers', []):
        try:
            captured = datetime.fromisoformat(offer['capturadoEn'])
            price = Decimal(str(offer['price']))
            url = offer['url']
            if (not offer.get('inStock') or offer.get('ram') != config['ram']
                    or not url.startswith('https://') or not price.is_finite() or price <= 0
                    or not timedelta(0) <= now - captured <= timedelta(hours=48)):
                continue
            # Descartar agrupaciones equivocadas de otras capacidades.
            capacities = {int(n) for n in re.findall(r'(?<![0-9])(128|256|512|1024)\s*(?:gb|giga)', url.lower())}
            if capacities and capacities != {config['capacity']}:
                continue
            eligible.append((price, url, offer.get('store', 'comercio'), captured.isoformat(timespec='minutes')))
        except (KeyError, ValueError, TypeError, ArithmeticError):
            continue
    if not eligible:
        raise ValueError('Sin precios externos recientes con memoria y stock confirmados')
    return min(eligible, key=lambda item: item[0])

def effective_price(p):
    regular = Decimal(str(p['precio']))
    discount = Decimal(str(p.get('descuento') or 0))
    discounted = Decimal(str(p.get('precio_con_descuento') or 0))
    price = discounted if discount > 0 and discounted > 0 else regular
    if not price.is_finite() or price <= 0:
        raise ValueError('Precio inválido')
    return price

def money(n):
    return '$' + f'{n:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

def ids_in_issues(api, token):
    found = set()
    for page in range(1,1001):
        issues = get_json(f'{api}/issues?state=all&per_page=100&page={page}', token=token)
        for issue in issues:
            found.update(MARKER.findall(issue.get('body') or ''))
        if len(issues) < 100:
            return found
    raise RuntimeError('Demasiadas incidencias')

def save_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)

def run(current, api, token):
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    rows, notices = [], []
    comparisons = {}
    try:
        catalog = fetch_market()
        market_error = None
    except Exception as exc:
        catalog = []
        market_error = str(exc)
    if market_error is None:
        save_json(MARKET_OUTPUT, export_market(catalog))
    for code, config in WATCH.items():
        previous = state.get(code, {'active': False, 'episode': 0})
        if code not in current:
            state[code] = {**previous, 'active': False}
            rows.append(f'- {code}: producto no disponible actualmente en el catálogo.')
            continue
        p = current[code]
        try:
            side = effective_price(p)
            if market_error:
                raise ValueError(market_error)
            market, market_url, seller, captured = market_price(config, catalog)
        except Exception as exc:
            print(f'No se pudo comparar {code}: {exc}', flush=True)
            rows.append(f'- {clean(p["titulo"])}: comparación temporalmente no disponible.')
            continue
        cheaper = side <= market * Decimal('0.80')
        if cheaper:
            # Conservamos tanto el precio en Side como la fecha de la referencia,
            # para que el tablero descarte datos vencidos o precios que cambiaron.
            comparisons[code] = {
                'tipo': 'modelo', 'precio_centavos': int(side * 100),
                'referencia_centavos': int(market * 100), 'referencia_tienda': seller,
                'referencia_url': market_url, 'ahorro_porcentaje': float(round((1 - side / market) * 100, 1)),
                'observado': captured + '-03:00', 'fuente': 'SoloPrecio',
            }
            matches = [item for item in catalog if item.get('id') == config['sku'] and item.get('inStock') is True]
            model = model_config(matches[0]) if len(matches) == 1 else None
            if model:
                refs = verified_offers(matches[0], config['ram'], config['capacity'], model[0], model[2])
                if len(refs) >= 2:
                    avg = int((Decimal(sum(ref['precio_centavos'] for ref in refs)) / len(refs)).quantize(Decimal('1')))
                    comparisons[code].update({
                        'referencia_centavos': avg,
                        'referencia_tienda': f'Promedio de {len(refs)} tiendas',
                        'referencia_url': refs[0]['url'],
                        'ahorro_porcentaje': round((1 - int(side * 100) / avg) * 100, 1),
                        'observado': min((ref['observado'] for ref in refs), key=datetime.fromisoformat),
                        'cantidad_referencias': len(refs), 'referencias': refs,
                    })
        episode = previous['episode'] + (1 if cheaper and not previous['active'] else 0)
        event_id = hashlib.sha256(f'{code}:{episode}:{side}'.encode()).hexdigest()[:20]
        side_url = 'https://sidecompras.com.ar/#/producto/' + quote(code, safe='')
        saving = (1 - side / market) * 100
        condition = ' Precio anunciado con bonificación en el resumen; sujeto a condiciones y elegibilidad.' if p.get('reintegro') else ''
        description = (f'[{clean(p["titulo"])}]({side_url}) — {clean(p.get("comercio"))}: **{money(side)}**. '
                       f'[Referencia en {clean(seller)}]({market_url}), relevada por SoloPrecio: **{money(market)}** (lectura {captured}, hora argentina). '
                       f'Diferencia: **{saving:.1f}%**. {"Cumple el criterio de oferta." if cheaper else "No cumple el criterio de oferta."}{condition}')
        rows.append('- ' + description)
        if cheaper and not previous['active']:
            notices.append((event_id, description))
        state[code] = {'active': cheaper, 'episode': episode}
    if notices:
        already = ids_in_issues(api, token)
        pending = [(event_id, description) for event_id, description in notices if event_id not in already]
        if pending:
            lines = ['Hola @gabyboan, encontré posibles ofertas comparando precios de productos equivalentes:', '']
            lines += ['- ' + description for _, description in pending]
            lines += ['', 'Los precios, stock, envío y condiciones pueden cambiar. Sidecompras puede requerir una tarjeta o promoción y la bonificación puede aplicarse después.', '']
            lines += [f'<!-- sidecompras-oferta:{event_id} -->' for event_id, _ in pending]
            result = get_json(api + '/issues', token=token, payload={'title': 'Sidecompras: posibles ofertas frente a otros comercios', 'body': '\n'.join(lines), 'assignees': ['gabyboan']})
            print('Ofertas avisadas:', result.get('html_url'), flush=True)
    save_json(STATE, state)
    save_json(COMPARISONS, {'version': 1, 'actualizado': datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec='seconds'),
                            'comparaciones': comparisons})
    content = ('# Comparaciones de precios de Sidecompras\n\n'
               'Se revisan los modelos de esta lista cada hora. Una posible oferta requiere que el precio anunciado en Sidecompras sea al menos 20% menor que el precio de un comercio relevado por SoloPrecio en las últimas 48 horas. '
               'La comparación cubre únicamente los modelos de abajo, no todo el catálogo; se usan fichas verificadas del mismo modelo y capacidad.\n\n'
               'Los precios pueden cambiar y SoloPrecio no incluye todas las tiendas. Revisá stock, envío y condiciones antes de comprar. '
               'Los precios con reintegro pueden aplicarse como bonificación posterior y dependen de la promoción.\n\n' + '\n'.join(rows) + '\n')
    LIST.write_text(content, encoding='utf-8')

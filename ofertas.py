from urllib.request import urlopen
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
import hashlib
import json
import os
import re

from monitor import clean, get_json

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'ofertas_estado.json'
LIST = ROOT / 'OFERTAS.md'
SOURCE = 'https://soloprecio.com.ar/data/comparador/celulares.json'
WATCH = {
    '22487-YB2EES': {'sku': 'phone_samsung_s26ultra_256gb_5g', 'ram': 12, 'capacity': 256},
    '22489-PERMWQ': {'sku': 'phone_samsung_a17_128gb_4gbram', 'ram': 4, 'capacity': 128},
    '22489-4S7VTY': {'sku': 'phone_samsung_a36_256gb_5g', 'ram': 8, 'capacity': 256},
    '22487-QABC42': {'sku': 'phone_motorola_motog15_128gb_4gbram', 'ram': 4, 'capacity': 128},
    '22487-J6KYC2': {'sku': 'phone_motorola_motog17_128gb_4gbram', 'ram': 4, 'capacity': 128},
}
MARKER = re.compile(r'<!-- sidecompras-oferta:([0-9a-f]{20}) -->')

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
    try:
        catalog = fetch_market()
        market_error = None
    except Exception as exc:
        catalog = []
        market_error = str(exc)
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
    content = ('# Comparaciones de precios de Sidecompras\n\n'
               'Se revisan los modelos de esta lista cada hora. Una posible oferta requiere que el precio anunciado en Sidecompras sea al menos 20% menor que el precio de un comercio relevado por SoloPrecio en las últimas 48 horas. '
               'La comparación cubre únicamente los modelos de abajo, no todo el catálogo; se usan fichas verificadas del mismo modelo y capacidad.\n\n'
               'Los precios pueden cambiar y SoloPrecio no incluye todas las tiendas. Revisá stock, envío y condiciones antes de comprar. '
               'Los precios con reintegro pueden aplicarse como bonificación posterior y dependen de la promoción.\n\n' + '\n'.join(rows) + '\n')
    LIST.write_text(content, encoding='utf-8')

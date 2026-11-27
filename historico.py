"""Control de bajas del precio publicado, separado de los avisos de productos."""
import base64
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

STATE = Path(__file__).resolve().parent / 'precios.json'
SITE = 'https://sidecompras.com.ar'
MARKER = re.compile(r'<!-- sidecompras-price-events:([A-Za-z0-9_=-]+) -->')


def _amount(value):
    """Devuelve centavos enteros para importes positivos; ignora datos inválidos."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        cents = number * 100
        if not number.is_finite() or number <= 0 or cents != cents.to_integral_value():
            return None
        return int(cents)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def effective_price(product):
    """Precio vigente publicado; no interpreta el precio tachado como vigente."""
    original = _amount(product.get('precio'))
    discounted = _amount(product.get('precio_con_descuento'))
    if _amount(product.get('descuento')) and discounted:
        return discounted
    return original


def _api(url, token, payload=None):
    headers = {'User-Agent': 'SidecomprasMonitor/1.0',
               'Accept': 'application/vnd.github+json',
               'Authorization': 'Bearer ' + token,
               'X-GitHub-Api-Version': '2022-11-28'}
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    if data is not None:
        headers['Content-Type'] = 'application/json'
    with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def _load():
    if not STATE.exists():
        return {}
    data = json.loads(STATE.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('productos'), dict):
        raise ValueError('Archivo de precios inválido')
    records = data['productos']
    for code, record in records.items():
        if (not isinstance(code, str) or not isinstance(record, dict)
                or type(record.get('centavos')) is not int or record['centavos'] <= 0
                or type(record.get('secuencia')) is not int or record['secuencia'] < 0):
            raise ValueError('Registro de precio inválido')
    return records


def _save(records):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'version': 1, 'productos': records},
                             ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                   encoding='utf-8')
    os.replace(tmp, STATE)


def _marker(ids):
    payload = json.dumps(ids, ensure_ascii=True, separators=(',', ':')).encode()
    return '<!-- sidecompras-price-events:' + base64.urlsafe_b64encode(payload).decode() + ' -->'


def _already_alerted(api, token):
    found = set()
    for page in range(1, 1001):
        issues = _api(f'{api}/issues?state=all&per_page=100&page={page}', token)
        if not isinstance(issues, list):
            raise ValueError('Respuesta inesperada de GitHub')
        for issue in issues:
            for match in MARKER.finditer(issue.get('body') or ''):
                ids = json.loads(base64.urlsafe_b64decode(match.group(1)))
                if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                    raise ValueError('Marcador de precios inválido')
                found.update(ids)
        if len(issues) < 100:
            return found
    raise RuntimeError('Demasiadas incidencias para comprobar avisos de precios')


def _clean(value):
    value = str(value or 'No informado').replace('@', '@\u200b').replace('\n', ' ').replace('\r', ' ')
    return re.sub(r'([\\`*_\[\]<>])', r'\\\1', value)


def _money(cents):
    whole, frac = divmod(cents, 100)
    text = f'{whole:,}'.replace(',', '.')
    return '$' + text + (f',{frac:02d}' if frac else '')


def _create_issue(api, token, events):
    lines = ['Hola @gabyboan, bajaron estos precios publicados en Sidecompras:', '']
    for event in events:
        p = event['product']
        url = SITE + '/#/producto/' + quote(p['codigo'], safe='')
        old, new = event['old'], event['new']
        percentage = (Decimal(old - new) * 100 / Decimal(old)).quantize(Decimal('0.1'))
        condition = ' (precio anunciado sujeto a condiciones de reintegro)' if p.get('reintegro') else ''
        lines.append(f"- [{_clean(p['titulo'])}]({url}) — {_clean(p.get('comercio'))}: "
                     f"{_money(old)} → {_money(new)} ({percentage}% menos){condition}")
    lines.extend(['', 'Comparación con el precio observado anteriormente en Sidecompras; '
                  'no es una comparación con otras tiendas.', '', _marker([e['id'] for e in events])])
    response = _api(api + '/issues', token, {
        'title': f"Sidecompras: {len(events)} baja(s) de precio",
        'body': '\n'.join(lines),
        'assignees': ['gabyboan'],
    })
    print('Aviso de bajas creado:', response.get('html_url'), flush=True)


def run(current, api, token):
    """Registra precios y avisa bajas de al menos 20 % frente a la última observación.

    Sin archivo previo establece la referencia sin alertas. Conserva productos ausentes
    y precios no disponibles, y guarda sólo después de crear los avisos correspondientes.
    """
    records = _load()
    next_records = dict(records)
    events = []
    for code, product in current.items():
        price = effective_price(product)
        if price is None:
            continue
        previous = records.get(code)
        if previous is None:
            next_records[code] = {'centavos': price, 'secuencia': 0}
            continue
        old, seq = previous['centavos'], previous['secuencia']
        if old == price:
            continue
        seq += 1
        next_records[code] = {'centavos': price, 'secuencia': seq}
        if price * 100 <= old * 80:
            # La secuencia cambia con cada cambio observado de precio y hace distinto
            # un nuevo episodio aun si vuelve a repetirse un precio anterior.
            event_id = json.dumps([code, seq, price], ensure_ascii=True, separators=(',', ':'))
            events.append({'id': event_id, 'product': product, 'old': old, 'new': price})
    unsent = events
    if events:
        already = _already_alerted(api, token)
        unsent = [event for event in events if event['id'] not in already]
        for offset in range(0, len(unsent), 50):
            _create_issue(api, token, unsent[offset:offset + 50])
    if next_records != records or not STATE.exists():
        _save(next_records)
    print(f'Precios: {len(next_records)} observados; bajas nuevas avisadas: {len(unsent)}.', flush=True)

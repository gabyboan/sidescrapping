#!/usr/bin/env python3
"""Detecta productos nuevos y crea avisos como incidencias de GitHub."""
import base64
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'estado.json'
SITE = 'https://sidecompras.com.ar'
MARKER = re.compile(r'<!-- sidecompras-codes:([A-Za-z0-9_=-]+) -->')


def get_json(url, *, token=None, payload=None):
    headers = {'User-Agent': 'SidecomprasMonitor/1.0', 'Accept': 'application/json'}
    if token:
        headers.update({'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                        'X-GitHub-Api-Version': '2022-11-28'})
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    if data is not None:
        headers['Content-Type'] = 'application/json'
    with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def fetch_catalog():
    for attempt in range(3):
        products = {}
        total = pages = None
        for page in range(1, 1001):
            data = get_json(f'{SITE}/api/buscar?orden=nuevos&pagina={page}')
            if page == 1:
                total, pages = data['total'], data['paginas']
                if not isinstance(total, int) or total < 1 or not isinstance(pages, int) or not 1 <= pages <= 1000:
                    raise ValueError('Tamaño de catálogo inesperado')
            if data.get('total') != total or data.get('paginas') != pages or data.get('pagina') != page:
                break
            items = data.get('productos')
            if not isinstance(items, list) or not items:
                break
            for item in items:
                code = item.get('codigo')
                if not isinstance(code, str) or not code or not item.get('titulo'):
                    raise ValueError('Producto sin código o título')
                products[code] = item
            if page == pages:
                if len(products) == total:
                    return products
                break
            time.sleep(.15)
        print(f'Catálogo incompleto ({len(products)}/{total}); reintentando', flush=True)
        time.sleep(2)
    raise RuntimeError('No se pudo obtener el catálogo completo; no se guardaron cambios')


def load_state():
    data = json.loads(STATE.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('vistos'), list):
        raise ValueError('Archivo de estado inválido')
    return set(data['vistos'])


def save_state(codes):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'version': 1, 'vistos': sorted(codes)}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, STATE)


def marker(codes):
    data = json.dumps(codes, ensure_ascii=True, separators=(',', ':')).encode()
    return '<!-- sidecompras-codes:' + base64.urlsafe_b64encode(data).decode() + ' -->'


def previously_alerted(api, token):
    found = set()
    for page in range(1, 1001):
        issues = get_json(f'{api}/issues?state=all&per_page=100&page={page}', token=token)
        if not isinstance(issues, list):
            raise ValueError('Respuesta inesperada de GitHub')
        for issue in issues:
            for match in MARKER.finditer(issue.get('body') or ''):
                codes = json.loads(base64.urlsafe_b64decode(match.group(1)).decode())
                if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
                    raise ValueError('Marcador de aviso inválido')
                found.update(codes)
        if len(issues) < 100:
            return found
    raise RuntimeError('Demasiadas páginas de incidencias para comprobar avisos previos')


def clean(value):
    # Evitar menciones y enlaces Markdown inesperados procedentes de la tienda.
    value = str(value or 'No informado').replace('@', '@\u200b').replace('\n', ' ').replace('\r', ' ')
    return re.sub(r'([\\`*_\[\]<>])', r'\\\1', value)


def create_issue(api, token, products, *, test=False):
    if test:
        title = 'Prueba de aviso de Sidecompras'
        body = ('Hola @gabyboan, esta es una prueba de las notificaciones del monitor. '
                'No representa un producto nuevo. Podés cerrar esta incidencia.')
    else:
        title = f'Sidecompras: {len(products)} producto(s) nuevos'
        lines = ['Hola @gabyboan, se detectaron estos productos nuevos en Sidecompras:\n']
        for p in products:
            price = p.get('precio_con_descuento') or p.get('precio') or 'No informado'
            url = SITE + '/#/producto/' + quote(p['codigo'], safe='')
            lines.append(f"- [{clean(p['titulo'])}]({url}) — {clean(p.get('comercio'))} — $ {clean(price)}")
        lines.extend(['', 'Productos detectados desde el inicio del monitoreo.', '', marker([p['codigo'] for p in products])])
        body = '\n'.join(lines)
    result = get_json(api + '/issues', token=token,
                      payload={'title': title, 'body': body, 'assignees': ['gabyboan']})
    print('Aviso creado:', result.get('html_url'), flush=True)


def main():
    token = os.environ['GH_TOKEN']
    repo = os.environ['GITHUB_REPOSITORY']
    api = 'https://api.github.com/repos/' + repo
    if '--prueba' in sys.argv:
        create_issue(api, token, [], test=True)
        return
    current = fetch_catalog()
    seen = load_state()
    fresh = [p for code, p in current.items() if code not in seen]
    if not fresh:
        print(f'Sin novedades. Catálogo: {len(current)} productos.')
        return
    already = previously_alerted(api, token)
    unsent = [p for p in fresh if p['codigo'] not in already]
    for i in range(0, len(unsent), 50):
        create_issue(api, token, unsent[i:i + 50])
    save_state(seen | current.keys())
    print(f'Nuevos: {len(fresh)}; avisados en esta ejecución: {len(unsent)}.')


if __name__ == '__main__':
    main()

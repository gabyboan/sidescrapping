"""Compara únicamente variantes identificadas por EAN y presentación explícita."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
from statistics import median
import unicodedata
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'comparaciones.json'
TZ = timezone(timedelta(hours=-3))
MEASURE = re.compile(r'(?<!\w)(\d+(?:[.,]\d+)?)\s*(kg|kilos?|g|grs?|gramos?|l|lts?|litros?|ml|cc|cm3|m|mts?)(?!\w)', re.I)
PACK = re.compile(r'(?<!\w)(\d+)\s*[xX]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|grs?|l|lts?|ml|cc|m|mts?)(?!\w)', re.I)


def valid_ean(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) not in (8, 12, 13, 14):
        return False
    if len(set(value)) == 1:
        return False
    return (sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(value[-2::-1])) + int(value[-1])) % 10 == 0


def presentation(title):
    """Sólo comparar si ambos títulos declaran la misma cantidad y tamaño de envase."""
    title = unicodedata.normalize('NFKC', str(title)).lower()
    matches = list(MEASURE.finditer(title))
    if len(matches) != 1:
        return None
    match = matches[0]
    unit = match.group(2)
    try:
        quantity = Decimal(match.group(1).replace(',', '.'))
    except InvalidOperation:
        return None
    if unit in ('kg', 'kilo', 'kilos'):
        unit, quantity = 'g', quantity * 1000
    elif unit in ('g', 'gr', 'grs', 'gramo', 'gramos'):
        unit = 'g'
    elif unit in ('l', 'lt', 'lts', 'litro', 'litros'):
        unit, quantity = 'ml', quantity * 1000
    elif unit in ('ml', 'cc', 'cm3'):
        unit = 'ml'
    else:
        unit = 'm'
    pack = PACK.search(title)
    # Tamaño del envase y cantidad de unidades, no solo peso total.
    count = int(pack.group(1)) if pack else 1
    if count < 1 or quantity <= 0:
        return None
    # Palabras como "pack 5u" pueden cambiar la presentación.
    count_suffix = re.search(r'\b(?:pack\s*)?(\d+)\s*(?:u|unidades?)\b', title)
    if count_suffix:
        explicit = int(count_suffix.group(1))
        if pack and explicit != count:
            return None
        count = explicit
    # Si se anuncia un combo o multiplicador sin presentación inequívoca, omitir.
    if re.search(r'\b(?:combo|bulto|caja|docena)\b', title) or re.search(r'(?:^|\s)x\s*\d+\s*$', title):
        return None
    return unit, quantity, count


def tokens(title):
    normalized = unicodedata.normalize('NFKD', str(title))
    normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch)).lower()
    stop = {'con', 'sin', 'para', 'por', 'pack', 'agua', 'gaseosa', 'leche', 'galletitas', 'cerveza', 'aceite', 'arroz'}
    return {w for w in re.findall(r'[a-z]{4,}', normalized) if w not in stop}


def qualifiers(title):
    """Conservar diferencias explícitas de variante que a veces comparten EAN erróneo."""
    normalized = unicodedata.normalize('NFKD', str(title))
    s = ''.join(ch for ch in normalized if not unicodedata.combining(ch)).lower()
    families = (
        ('semidescremado', 'descremado', 'entero'),
        ('sin azucar', 'zero azucar', 'con azucar'),
        ('sin alcohol', 'cero alcohol', 'con alcohol'),
        ('no retornable', 'retornable'),
        ('vainilla', 'frutilla', 'chocolate', 'manzana', 'pomelo', 'limon'),
        ('integral',),
        ('rex',),
    )
    result = []
    for family in families:
        # Priorizar las expresiones más largas para que «no retornable» no
        # también coincida con «retornable», ni «semidescremado» con «descremado».
        found = []
        remaining = s
        for term in sorted(family, key=len, reverse=True):
            pattern = r'(?<![a-z])' + re.escape(term) + r'(?:s|a|as)?(?![a-z])'
            if re.search(pattern, remaining):
                found.append(term)
                remaining = re.sub(pattern, ' ', remaining)
        result.append(tuple(sorted(found)))
    # Sin la medida física, los números restantes identifican presentación o
    # variedad (por ejemplo N°5 y N°11); no suponer equivalencia si falta uno.
    stripped = MEASURE.sub(' ', s)
    result.append(tuple(re.findall(r'(?<![\w.])\d+(?![\w.])', stripped)))
    return tuple(result)


def observed(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def compatible(first, second):
    a, b = first.get('titulo'), second.get('titulo')
    size = presentation(a)
    return bool(size and size == presentation(b) and tokens(a) & tokens(b)
                and qualifiers(a) == qualifiers(b))


def usable_product(p):
    try:
        url = urlsplit(p.get('url', ''))
        return (p.get('disponible') is True and type(p.get('precio_vigente_centavos')) is int
                and p['precio_vigente_centavos'] > 0 and isinstance(p.get('codigo'), str)
                and bool(p['codigo']) and url.scheme == 'https' and bool(url.netloc))
    except (TypeError, ValueError):
        return False


def central_references(entries):
    """Eliminar extremos evidentes antes de calcular el promedio.

    Con solo dos referencias muy dispares conservamos la menor, porque no hay
    evidencia suficiente para que la mayor eleve artificialmente la oferta.
    Con tres o más se usa la mediana para descartar valores fuera de 0,5-2x.
    """
    entries = sorted(entries, key=lambda entry: entry[1]['precio_vigente_centavos'])
    if len(entries) == 2 and entries[1][1]['precio_vigente_centavos'] > 2 * entries[0][1]['precio_vigente_centavos']:
        return entries[:1]
    if len(entries) >= 3:
        middle = median(entry[1]['precio_vigente_centavos'] for entry in entries)
        return [entry for entry in entries if middle / 2 <= entry[1]['precio_vigente_centavos'] <= middle * 2]
    return entries


def compare(data, now=None):
    now = now or datetime.now(TZ)
    groups = defaultdict(list)
    for store in data.get('tiendas', []):
        timestamp = observed(store.get('actualizado'))
        if (store.get('error') or not store.get('id') or not store.get('nombre')
                or not timestamp or not timedelta(0) <= now - timestamp <= timedelta(hours=48)):
            continue
        for p in store.get('productos', []):
            ean = p.get('ean')
            if valid_ean(ean):
                groups[ean].append((store, p, timestamp))
    result = {}
    for ean, entries in groups.items():
        # Si una tienda publica varias fichas con este EAN, no se puede decidir
        # cuál es la variante correcta, pero las demás siguen siendo utilizables.
        store_counts = defaultdict(int)
        for store, _, _ in entries:
            store_counts[store['id']] += 1
        entries = [entry for entry in entries if store_counts[entry[0]['id']] == 1 and usable_product(entry[1])]
        for candidate in entries:
            price = candidate[1]['precio_vigente_centavos']
            refs = [entry for entry in entries if entry is not candidate and compatible(candidate[1], entry[1])]
            # Evitar agrupar referencias que coinciden con la candidata pero se
            # contradicen entre sí (por ejemplo por variante mal catalogada).
            if any(not compatible(a[1], b[1]) for i, a in enumerate(refs) for b in refs[i + 1:]):
                continue
            # Una referencia promedio no convierte en mejor oferta a una
            # tienda que ya tiene otra más barata dentro del mismo grupo.
            if any(price > entry[1]['precio_vigente_centavos'] for entry in refs):
                continue
            refs = central_references(refs)
            if not refs:
                continue
            reference = (sum(entry[1]['precio_vigente_centavos'] for entry in refs) + len(refs) // 2) // len(refs)
            if price >= reference:
                continue
            ref_rows = [{'tienda': store['nombre'], 'precio_centavos': p['precio_vigente_centavos'],
                         'url': p['url'], 'observado': timestamp.isoformat()}
                        for store, p, timestamp in refs]
            result[candidate[1]['codigo']] = {
                'tipo': 'ean', 'ean': ean, 'precio_centavos': price,
                'referencia_centavos': reference, 'referencia_tienda': refs[0][0]['nombre'],
                'referencia_url': refs[0][1]['url'], 'referencias': ref_rows,
                'cantidad_referencias': len(ref_rows),
                'ahorro_porcentaje': round((reference - price) * 100 / reference, 1),
                'observado': min([candidate[2]] + [entry[2] for entry in refs]).isoformat(),
            }
    return {'version': 1, 'actualizado': now.isoformat(), 'comparaciones': result}


def write(data, output=OUTPUT):
    result = compare(data)
    tmp = output.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    return result


if __name__ == '__main__':
    data = json.loads((ROOT / 'supermercados.json').read_text(encoding='utf-8'))
    print('Comparaciones válidas:', len(write(data)['comparaciones']))

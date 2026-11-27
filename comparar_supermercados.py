"""Compara únicamente variantes identificadas por EAN y presentación explícita."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import unicodedata

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


def compare(data, now=None):
    now = now or datetime.now(TZ)
    groups = defaultdict(list)
    for store in data.get('tiendas', []):
        timestamp = observed(store.get('actualizado'))
        if store.get('error') or not timestamp or not timedelta(0) <= now - timestamp <= timedelta(hours=48):
            continue
        for p in store.get('productos', []):
            ean = p.get('ean')
            if valid_ean(ean):
                groups[ean].append((store, p, timestamp))
    result = {}
    for ean, entries in groups.items():
        # SKU duplicados o variantes del mismo EAN por tienda hacen ambigua la comparación.
        if len(entries) != 2 or entries[0][0].get('id') == entries[1][0].get('id'):
            continue
        first, second = entries
        p1, p2 = first[1], second[1]
        if any(p.get('disponible') is not True or type(p.get('precio_vigente_centavos')) is not int
               or p['precio_vigente_centavos'] <= 0 or not p.get('codigo') or not p.get('url') for p in (p1, p2)):
            continue
        presentation1, presentation2 = presentation(p1.get('titulo')), presentation(p2.get('titulo'))
        if (not presentation1 or presentation1 != presentation2
                or not tokens(p1.get('titulo')) & tokens(p2.get('titulo'))
                or qualifiers(p1.get('titulo')) != qualifiers(p2.get('titulo'))):
            continue
        cheap, expensive = sorted(entries, key=lambda entry: entry[1]['precio_vigente_centavos'])
        price, reference = cheap[1]['precio_vigente_centavos'], expensive[1]['precio_vigente_centavos']
        if price * 100 > reference * 80:
            continue
        result[cheap[1]['codigo']] = {
            'tipo': 'ean', 'ean': ean, 'precio_centavos': price,
            'referencia_centavos': reference, 'referencia_tienda': expensive[0]['nombre'],
            'referencia_url': expensive[1]['url'], 'ahorro_porcentaje': round((reference - price) * 100 / reference, 1),
            'observado': min(cheap[2], expensive[2]).isoformat(),
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

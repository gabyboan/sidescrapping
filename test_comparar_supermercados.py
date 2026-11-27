import copy
from datetime import datetime, timedelta, timezone
import unittest

from comparar_supermercados import compare, presentation, valid_ean


NOW = datetime(2026, 11, 27, 12, tzinfo=timezone(timedelta(hours=-3)))


def sample():
    p = {'codigo': 'uno', 'titulo': 'Gaseosa Pepsi Black sin azucar 2 L', 'ean': '7791813828464',
         'precio_vigente_centavos': 20000, 'disponible': True, 'url': 'https://uno.test/producto'}
    q = dict(p, codigo='dos', titulo='Pepsi Black Gaseosa sin azucar 2000 Ml', precio_vigente_centavos=30000,
             url='https://dos.test/producto')
    return {'tiendas': [
        {'id': 'uno', 'nombre': 'Uno', 'error': None, 'actualizado': NOW.isoformat(), 'productos': [p]},
        {'id': 'dos', 'nombre': 'Dos', 'error': None, 'actualizado': NOW.isoformat(), 'productos': [q]},
    ]}


class ComparisonTests(unittest.TestCase):
    def test_genuine_barcode_and_size(self):
        result = compare(sample(), NOW)['comparaciones']['uno']
        self.assertEqual(result['referencia_tienda'], 'Dos')
        self.assertEqual(result['ahorro_porcentaje'], 33.3)
        self.assertEqual(result['precio_centavos'], 20000)
        self.assertTrue(valid_ean('7791813828464'))
        self.assertFalse(valid_ean('7791813828465'))

    def test_different_size_pack_and_name_are_excluded(self):
        for title in ('Gaseosa Pepsi Black 1 L', 'Gaseosa Pepsi Black 2 L pack 4u', 'Gaseosa Cola 2 L'):
            data = sample()
            data['tiendas'][1]['productos'][0]['titulo'] = title
            self.assertEqual(compare(data, NOW)['comparaciones'], {}, title)
        self.assertNotEqual(presentation('Agua 4 x 80 m'), presentation('Agua 80 m'))

    def test_rejects_expired_or_future_observations_and_source_failures(self):
        for modified in (NOW - timedelta(hours=49), NOW + timedelta(minutes=1)):
            data = sample()
            data['tiendas'][1]['actualizado'] = modified.isoformat()
            self.assertEqual(compare(data, NOW)['comparaciones'], {})
        data = sample()
        data['tiendas'][1]['error'] = 'fallo de red'
        self.assertEqual(compare(data, NOW)['comparaciones'], {})

    def test_misclassified_variants_are_excluded_even_with_identical_barcode(self):
        pairs = [
            ('Yogur frutilla firme semidescremado marca 120 g', 'Yogur frutilla firme entero marca 120 g'),
            ('Yogur vainilla semidescremado marca 120 g', 'Yogur vainilla marca 120 g'),
            ('Fideos Matarazzo tallarin N°11 500 g', 'Fideos Matarazzo tallarin N°5 500 g'),
            ('Fideos Matarazzo tirabuzon 34 vegetales 500 g', 'Fideos Matarazzo tirabuzon 3 vegetales 500 g'),
            ('Cerveza Brahma retornable 710 ml', 'Cerveza Brahma no retornable 710 ml'),
            ('Galletitas Traviata sabor original 96 g', 'Galletitas Traviata Rex sabor original 96 g'),
        ]
        for first, second in pairs:
            data = sample()
            data['tiendas'][0]['productos'][0]['titulo'] = first
            data['tiendas'][1]['productos'][0]['titulo'] = second
            self.assertEqual(compare(data, NOW)['comparaciones'], {}, (first, second))

    def test_excludes_unavailable_duplicate_and_small_difference(self):
        data = sample()
        data['tiendas'][1]['productos'][0]['disponible'] = False
        self.assertEqual(compare(data, NOW)['comparaciones'], {})
        data = sample()
        data['tiendas'][1]['productos'].append(copy.deepcopy(data['tiendas'][1]['productos'][0]))
        self.assertEqual(compare(data, NOW)['comparaciones'], {})
        data = sample()
        data['tiendas'][1]['productos'][0]['precio_vigente_centavos'] = 24000
        self.assertEqual(compare(data, NOW)['comparaciones'], {})


if __name__ == '__main__':
    unittest.main()

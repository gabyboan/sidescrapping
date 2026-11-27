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

    def test_excludes_unavailable_and_duplicate_but_keeps_small_difference(self):
        data = sample()
        data['tiendas'][1]['productos'][0]['disponible'] = False
        self.assertEqual(compare(data, NOW)['comparaciones'], {})
        data = sample()
        data['tiendas'][1]['productos'].append(copy.deepcopy(data['tiendas'][1]['productos'][0]))
        self.assertEqual(compare(data, NOW)['comparaciones'], {})
        data = sample()
        data['tiendas'][1]['productos'][0]['precio_vigente_centavos'] = 24000
        self.assertEqual(compare(data, NOW)['comparaciones']['uno']['ahorro_porcentaje'], 16.7)

    def test_multiple_references_expose_prices_and_average(self):
        data = sample()
        third = copy.deepcopy(data['tiendas'][1])
        third.update(id='tres', nombre='Tres')
        third['productos'][0].update(codigo='tres', precio_vigente_centavos=40000,
                                     url='https://tres.test/producto')
        data['tiendas'].append(third)
        item = compare(data, NOW)['comparaciones']['uno']
        self.assertEqual(item['referencia_centavos'], 35000)
        self.assertEqual(item['cantidad_referencias'], 2)
        self.assertEqual([(r['tienda'], r['precio_centavos']) for r in item['referencias']],
                         [('Dos', 30000), ('Tres', 40000)])
        self.assertEqual(item['ahorro_porcentaje'], 42.9)

    def test_only_lowest_price_or_tie_can_be_featured(self):
        data = sample()
        third = copy.deepcopy(data['tiendas'][1])
        third.update(id='tres', nombre='Tres')
        third['productos'][0].update(codigo='tres', precio_vigente_centavos=40000,
                                     url='https://tres.test/producto')
        data['tiendas'][1]['productos'][0]['precio_vigente_centavos'] = 29000
        data['tiendas'].append(third)
        result = compare(data, NOW)['comparaciones']
        self.assertIn('uno', result)
        # 29000 está por debajo del promedio 30000, pero otra tienda cobra 20000.
        self.assertNotIn('dos', result)
        data['tiendas'][1]['productos'][0]['precio_vigente_centavos'] = 20000
        result = compare(data, NOW)['comparaciones']
        self.assertIn('uno', result)
        self.assertIn('dos', result)

    def test_outlier_does_not_inflate_comparison(self):
        data = sample()
        for store_id, price in [('tres', 40000), ('cuatro', 900000)]:
            store = copy.deepcopy(data['tiendas'][1])
            store.update(id=store_id, nombre=store_id)
            store['productos'][0].update(codigo=store_id, precio_vigente_centavos=price,
                                         url=f'https://{store_id}.test/producto')
            data['tiendas'].append(store)
        item = compare(data, NOW)['comparaciones']['uno']
        self.assertEqual(item['referencia_centavos'], 35000)
        self.assertEqual(item['cantidad_referencias'], 2)
        data['tiendas'].pop(2)
        item = compare(data, NOW)['comparaciones']['uno']
        self.assertEqual(item['referencia_centavos'], 30000)
        self.assertEqual(item['cantidad_referencias'], 1)

    def test_one_ambiguous_store_does_not_suppress_other_comparisons(self):
        data = sample()
        third = copy.deepcopy(data['tiendas'][1])
        third.update(id='tres', nombre='Tres')
        third['productos'][0].update(codigo='tres', precio_vigente_centavos=40000,
                                     url='https://tres.test/producto')
        third['productos'].append(copy.deepcopy(third['productos'][0]))
        data['tiendas'].append(third)
        item = compare(data, NOW)['comparaciones']['uno']
        self.assertEqual(item['cantidad_referencias'], 1)
        self.assertEqual(item['referencias'][0]['tienda'], 'Dos')
        self.assertNotIn('tres', compare(data, NOW)['comparaciones'])

    def test_three_store_variants_are_not_averaged(self):
        data = sample()
        third = copy.deepcopy(data['tiendas'][1])
        third.update(id='tres', nombre='Tres')
        third['productos'][0].update(codigo='tres', titulo='Gaseosa Pepsi con azucar 2 L',
                                     url='https://tres.test/producto')
        data['tiendas'].append(third)
        item = compare(data, NOW)['comparaciones']['uno']
        self.assertEqual(item['cantidad_referencias'], 1)
        self.assertEqual(item['referencias'][0]['tienda'], 'Dos')


if __name__ == '__main__':
    unittest.main()

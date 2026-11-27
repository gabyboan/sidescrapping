import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import exportar_supermercados as export

XTR = {'id': 'xtr', 'nombre': 'XTR', 'error': None, 'productos': [],
       'cobertura': {'productos_consultados': 0, 'total_publicado': None}}

def product(pid, price=120, listed=150, quantity=3):
    return {'productId': pid, 'productName': 'Leche', 'categories': ['/Almacén/Lácteos/'],
            'link': 'https://www.vea.com.ar/leche/p',
            'items': [{'itemId': pid, 'ean': '7791234567890',
                       'images': [{'imageUrl': 'https://jumboargentina.vteximg.com.br/img.jpg'}],
                       'sellers': [{'sellerDefault': True, 'commertialOffer': {
                           'Price': price, 'ListPrice': listed, 'AvailableQuantity': quantity}}]}]}


class SupermarketExportTests(unittest.TestCase):
    def test_uses_current_price_and_handles_unavailable(self):
        p = export.variants(export.STORES[0], product('123', 120.50, 150))[0]
        self.assertEqual(p['precio_vigente_centavos'], 12050)
        self.assertEqual(p['precio_centavos'], 15000)
        self.assertEqual(p['ean'], '7791234567890')
        unavailable = export.variants(export.STORES[0], product('123', quantity=0))[0]
        self.assertFalse(unavailable['disponible'])
        self.assertIsNone(unavailable['precio_vigente_centavos'])

    def test_complete_requires_verified_total(self):
        pages = [('0-1/3', [product('1'), product('2')]), ('2-2/3', [product('3')])]
        with patch.object(export, 'fetch_page', side_effect=pages), patch.object(export.time, 'sleep'):
            result = export.collect(export.STORES[0], max_pages=2, page_size=2)
        self.assertIsNone(result['error'])
        self.assertTrue(result['cobertura']['completa'])
        self.assertEqual(result['cobertura']['productos_consultados'], 3)

    def test_page_cap_reports_partial(self):
        with patch.object(export, 'fetch_page', return_value=('0-1/10', [product('1'), product('2')])):
            result = export.collect(export.STORES[0], max_pages=1, page_size=2)
        self.assertFalse(result['cobertura']['completa'])
        self.assertTrue(result['cobertura']['limitada'])
        self.assertEqual(result['cobertura']['total_publicado'], 10)

    def test_changed_total_and_duplicates_are_not_full_coverage(self):
        for second in [('2-3/1000', [product('3'), product('4')]),
                       ('2-3/4', [product('1'), product('4')])]:
            pages = [('0-1/4', [product('1'), product('2')]), second]
            with self.subTest(second=second), patch.object(export, 'fetch_page', side_effect=pages), patch.object(export.time, 'sleep'):
                result = export.collect(export.STORES[0], max_pages=2, page_size=2)
                self.assertFalse(result['cobertura']['completa'])
                self.assertIsNotNone(result['error'])

    def test_small_total_variation_is_usable_but_never_complete(self):
        pages = [('0-1/4', [product('1'), product('2')]), ('2-3/5', [product('3'), product('4')])]
        with patch.object(export, 'fetch_page', side_effect=pages), patch.object(export.time, 'sleep'):
            result = export.collect(export.STORES[0], max_pages=2, page_size=2)
        self.assertIsNone(result['error'])
        self.assertIsNotNone(result['advertencia'])
        self.assertFalse(result['cobertura']['completa'])
        self.assertEqual(len(result['productos']), 4)

    def test_one_store_failure_is_recorded_without_hiding_other(self):
        def page(store, start, size):
            if store['id'] == 'vea':
                raise OSError('No disponible')
            return '0-0/1', [product('1')]
        with tempfile.TemporaryDirectory() as d, patch.object(export, 'fetch_page', side_effect=page), patch.object(export.exportar_xtr, 'collect', return_value=XTR):
            path = Path(d) / 'sample.json'
            result = export.run(max_pages=1, output=path)
            self.assertIsNotNone(result['tiendas'][0]['error'])
            self.assertTrue(result['tiendas'][1]['cobertura']['completa'])
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), result)

    def test_failure_keeps_last_successful_store_with_original_date(self):
        previous = {'version': 1, 'tiendas': [{'id': 'vea', 'nombre': 'Vea', 'actualizado': 'fecha-anterior',
                    'productos': [{'codigo': 'guardado'}], 'cobertura': {'productos_consultados': 1, 'total_publicado': 4}}]}
        def page(store, start, size):
            if store['id'] == 'vea':
                raise OSError('No disponible')
            return '0-0/1', [product('1')]
        with tempfile.TemporaryDirectory() as d, patch.object(export, 'fetch_page', side_effect=page), patch.object(export.exportar_xtr, 'collect', return_value=XTR):
            path = Path(d) / 'sample.json'
            path.write_text(json.dumps(previous), encoding='utf-8')
            result = export.run(max_pages=1, output=path)['tiendas'][0]
            self.assertEqual(result['actualizado'], 'fecha-anterior')
            self.assertEqual(result['productos'][0]['codigo'], 'guardado')
            self.assertTrue(result['error'])
            self.assertTrue(result['intento_actualizado'])


if __name__ == '__main__':
    unittest.main()

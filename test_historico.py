import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import historico


def product(price, *, discounted=None, discount=None, reintegro=False):
    return {'codigo': '123-A', 'titulo': 'Equipo', 'comercio': 'Tienda',
            'precio': price, 'precio_con_descuento': discounted,
            'descuento': discount, 'reintegro': reintegro}


class PriceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = patch.object(historico, 'STATE', Path(self.temp.name) / 'precios.json')
        self.state.start()
        self.addCleanup(self.state.stop)
        self.issues = []
        self.network = patch.object(historico, '_api', side_effect=self.api)
        self.network.start()
        self.addCleanup(self.network.stop)

    def api(self, url, token, payload=None):
        if payload is not None:
            self.issues.append(payload)
            return {'html_url': 'https://github.test/issue'}
        return self.issues[:]

    def run_catalog(self, item):
        historico.run({'123-A': item}, 'https://github.test/api', 'token')

    def test_actual_price_ignores_crossed_out_price_and_validates_discount(self):
        self.assertEqual(historico.effective_price(product('2599000', discounted='1299500', discount='50')), 129950000)
        self.assertEqual(historico.effective_price(product('2599000', discounted='1299500', discount=None)), 259900000)
        self.assertEqual(historico.effective_price(product('2599000', discounted='0', discount='50')), 259900000)
        self.assertIsNone(historico.effective_price(product('NaN')))

    def test_baseline_then_threshold_rebound_and_repeat(self):
        self.run_catalog(product('1000'))
        self.assertEqual(len(self.issues), 0)
        self.run_catalog(product('801'))
        self.assertEqual(len(self.issues), 0)
        # 19.98 % against the immediately preceding observation: no alert.
        self.run_catalog(product('641'))
        self.assertEqual(len(self.issues), 0)
        self.run_catalog(product('1000'))
        self.run_catalog(product('800', reintegro=True))
        self.assertEqual(len(self.issues), 1)
        self.assertIn('$1.000 → $800 (20.0% menos)', self.issues[0]['body'])
        self.assertIn('condiciones de reintegro', self.issues[0]['body'])
        self.run_catalog(product('800'))
        self.assertEqual(len(self.issues), 1)
        self.run_catalog(product('1000'))
        self.run_catalog(product('800'))
        self.assertEqual(len(self.issues), 2)

    def test_issue_created_before_failed_state_save_is_not_duplicated(self):
        self.run_catalog(product('1000'))
        with patch.object(historico, '_save', side_effect=OSError('disco')):
            with self.assertRaises(OSError):
                self.run_catalog(product('500'))
        self.assertEqual(len(self.issues), 1)
        self.run_catalog(product('500'))
        self.assertEqual(len(self.issues), 1)
        self.run_catalog(product('500'))
        self.assertEqual(len(self.issues), 1)

    def test_invalid_current_price_does_not_erase_last_good_observation(self):
        self.run_catalog(product('1000'))
        self.run_catalog(product(None))
        self.run_catalog(product('700'))
        self.assertEqual(len(self.issues), 1)

    def test_failure_to_create_issue_does_not_advance_state(self):
        self.run_catalog(product('1000'))
        with patch.object(historico, '_create_issue', side_effect=OSError('GitHub')):
            with self.assertRaises(OSError):
                self.run_catalog(product('500'))
        self.run_catalog(product('500'))
        self.assertEqual(len(self.issues), 1)


if __name__ == '__main__':
    unittest.main()

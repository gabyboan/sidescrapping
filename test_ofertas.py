import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import ofertas

class Comparisons(unittest.TestCase):
    def test_effective_discount(self):
        self.assertEqual(ofertas.effective_price({'precio':'100','descuento':'0','precio_con_descuento':'20'}),100)
        self.assertEqual(ofertas.effective_price({'precio':'100','descuento':'50','precio_con_descuento':'50'}),50)

    def test_fresh_correct_variant_only(self):
        now=datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None, microsecond=0).isoformat()
        config={'sku':'model','ram':4,'capacity':128}
        offers=[{'price':10,'url':'https://example.com/512gb','ram':4,'inStock':True,'capturadoEn':now},
                {'price':15,'url':'https://example.com/128gb','ram':8,'inStock':True,'capturadoEn':now},
                {'price':20,'url':'https://example.com/128gb','ram':4,'inStock':True,'capturadoEn':now},
                {'price':1,'url':'https://example.com/128gb','ram':4,'inStock':True,'capturadoEn':'2000-01-01T00:00:00'}]
        catalog=[{'id':'model','inStock':True,'offers':offers}]
        self.assertEqual(ofertas.market_price(config,catalog)[0],20)

    def test_retry_and_new_episode(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ofertas,'STATE',Path(tmp)/'state.json'), patch.object(ofertas,'LIST',Path(tmp)/'list.md'), patch.object(ofertas,'COMPARISONS',Path(tmp)/'comparaciones.json'), patch.object(ofertas,'MARKET_OUTPUT',Path(tmp)/'mercado.json'), patch.object(ofertas,'WATCH',{'x':{'sku':'m'}}), patch.object(ofertas,'fetch_market',return_value=[]), patch.object(ofertas,'market_price',return_value=(100,'https://example.com','Shop','2026-01-01T12:00')):
            calls=[]
            def api(url, token=None, payload=None):
                if payload is None: return []
                calls.append(payload)
                return {'html_url':'https://example.com'}
            product={'codigo':'x','titulo':'Product','precio':'50','descuento':'0'}
            with patch.object(ofertas,'get_json',side_effect=api):
                ofertas.run({'x':product},'https://api.example','test')
                ofertas.run({'x':product},'https://api.example','test')
                self.assertEqual(len(calls),1)
                product['precio']='90'
                ofertas.run({'x':product},'https://api.example','test')
                product['precio']='50'
                ofertas.run({'x':product},'https://api.example','test')
                self.assertEqual(len(calls),2)

    def test_market_average_only_matching_distinct_stores(self):
        now = datetime(2026, 11, 27, 12, tzinfo=timezone(timedelta(hours=-3)))
        def offer(store, price, url, **extra):
            return {'store':store, 'price':price, 'url':url, 'ram':8, 'inStock':True,
                    'trusted':True, 'capturadoEn':'2026-11-27T10:00:00', **extra}
        offers = [offer('A', 50, 'https://a.example/samsung-galaxy-a36-5g-8gb-256gb'),
                  offer('B', 100, 'https://b.example/samsung-galaxy-a36-5g-256gb'),
                  offer('C', 200, 'https://c.example/samsung-galaxy-a36-5g-256gb'),
                  offer('C', 300, 'https://c.example/samsung-a36-5g-256gb'),
                  offer('Wrong capacity', 1, 'https://d.example/samsung-a36-5g-128gb'),
                  offer('Power variant', 1, 'https://e.example/samsung-a36-power-5g-256gb'),
                  offer('Wrong network', 1, 'https://f.example/samsung-a36-4g-256gb'),
                  offer('Wrong ram', 1, 'https://g.example/samsung-a36-5g-256gb', ram=4),
                  offer('No capacity', 1, 'https://h.example/samsung-a36-5g'),
                  offer('Dollars', 1, 'https://i.example/samsung-a36-5g-256gb', currency='USD'),
                  offer('Old', 1, 'https://j.example/samsung-a36-5g-256gb', capturadoEn='2000-01-01T00:00:00')]
        product = {'id':'phone_samsung_a36_256gb_5g', 'name':'Samsung A36 5G 8GB 256GB',
                   'isVerified':True, 'inStock':True, 'offers':offers}
        output = ofertas.export_market([product], now)
        self.assertEqual(len(output['productos']), 1)
        p = output['productos'][0]
        self.assertEqual(p['origen'], 'A')
        comparison = output['comparaciones'][p['codigo']]
        self.assertEqual(comparison['referencia_centavos'], 15000)
        self.assertEqual(comparison['cantidad_referencias'], 2)
        self.assertEqual({r['tienda'] for r in comparison['referencias']}, {'B','C'})
        self.assertEqual(comparison['ahorro_porcentaje'], 66.7)

    def test_market_requires_two_distinct_references(self):
        now = datetime(2026, 11, 27, 12, tzinfo=timezone(timedelta(hours=-3)))
        one = {'store':'A','price':1,'url':'https://a.example/samsung-a36-5g-256gb','ram':8,
               'inStock':True,'trusted':True,'capturadoEn':'2026-11-27T10:00:00'}
        product = {'id':'phone_samsung_a36_256gb_5g','name':'Samsung A36 5G','isVerified':True,
                   'inStock':True,'offers':[one, {**one,'price':100}]}
        self.assertEqual(ofertas.export_market([product], now)['productos'], [])

if __name__=='__main__': unittest.main()

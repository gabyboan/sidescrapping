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
        with tempfile.TemporaryDirectory() as tmp, patch.object(ofertas,'STATE',Path(tmp)/'state.json'), patch.object(ofertas,'LIST',Path(tmp)/'list.md'), patch.object(ofertas,'COMPARISONS',Path(tmp)/'comparaciones.json'), patch.object(ofertas,'WATCH',{'x':{'sku':'m'}}), patch.object(ofertas,'fetch_market',return_value=[]), patch.object(ofertas,'market_price',return_value=(100,'https://example.com','Shop','2026-01-01T12:00')):
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

if __name__=='__main__': unittest.main()

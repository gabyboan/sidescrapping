import html
import json
import unittest

import exportar_xtr as export


class XtrPromotionsTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://www.xtr.com.ar/productos/articulo/'
        self.product = {'@type': 'Product', 'sku': 'A1', 'name': 'Producto', 'offers': {
            'url': self.url, 'priceCurrency': 'ARS', 'price': '100',
            'availability': 'https://schema.org/InStock'}}

    def card(self, *, price=10000, discount=9500, medium='Transferencia', variants=None, href=None):
        if variants is None:
            variants = [{'sku': 'A1', 'price_number_raw': price}]
        encoded = html.escape(json.dumps(variants), quote=True)
        return f'''<div class="js-item-product"><div data-variants="{encoded}">
        <a href="{href or self.url + '?entry_path=category'}">Producto</a>
        <span class="js-price-display" data-product-price="{price}"></span>
        <div class="js-payment-discount-price-product-container">
        <span class="js-payment-discount-price-product" data-priceraw-without-shipping="{discount}"></span>
        <span class="js-payment-discount-name-product">{medium}</span></div></div></div>'''

    def parse(self, cards):
        parser = export.ProductParser()
        parser.feed(cards + '<script type="application/ld+json">' + json.dumps(self.product) + '</script>')
        return export._product(parser.products[0], parser.cards)

    def test_verified_transfer_price_is_separate(self):
        result = self.parse(self.card())
        self.assertEqual(result['precio_vigente_centavos'], 10000)
        self.assertEqual(result['promociones'][0]['precio_centavos'], 9500)
        self.assertEqual(result['promociones'][0]['medio'], 'Transferencia')

    def test_unverifiable_or_ambiguous_cards_have_no_promotion(self):
        variants = [{'sku': 'A1', 'price_number_raw': 10000}, {'sku': 'A2', 'price_number_raw': 10000}]
        examples = [self.card(medium='Efectivo'), self.card(price=9000), self.card(discount=10000),
                    self.card(href='https://www.xtr.com.ar/productos/otro/'), self.card(variants=variants),
                    self.card() + self.card()]
        for card in examples:
            with self.subTest(card=card):
                self.assertEqual(self.parse(card)['promociones'], [])
        self.product['offers']['availability'] = 'https://schema.org/OutOfStock'
        self.assertEqual(self.parse(self.card())['promociones'], [])


if __name__ == '__main__':
    unittest.main()

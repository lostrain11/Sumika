import unittest

from tools.read_siliconflow_public_pricing import free_text_rows


class PublicPricingTests(unittest.TestCase):
    def row(self, model="vendor/text", prices=None, category="text"):
        prices = prices or ["\u514d\u8d39", "\u514d\u8d39", "-"]
        cells = f"<div><span>Text</span><div>{model}</div></div>" + "".join(f"<div>{price}</div>" for price in prices)
        return f'<div id="pricing-row-{category}-1">{cells}</div>'

    def test_exact_row_scoping_and_unknown_cache_not_promoted(self):
        rows = free_text_rows(self.row() + self.row("vendor/paid", ["1.0", "2.0", "-"]))
        self.assertEqual(rows, [{"model_id": "vendor/text", "input_price_label": "free",
                                 "output_price_label": "free", "cache_price_label": "not-quoted"}])

    def test_all_required_prices_and_text_category(self):
        for row in (self.row(prices=["\u514d\u8d39", "1.0", "-"]), self.row(category="image"),
                    self.row(prices=["\u514d\u8d39", "\u514d\u8d39", "1.0"]),
                    self.row(prices=["\u9650\u65f6\u514d\u8d39", "\u514d\u8d39", "-"])):
            with self.assertRaises(ValueError):
                free_text_rows(row)

    def test_duplicate_and_incomplete_rows_are_rejected(self):
        for html in (self.row() + self.row(), self.row()[:-6], "<div>free vendor/model</div>"):
            with self.assertRaises(ValueError):
                free_text_rows(html)

    def test_nested_price_rows_do_not_mix_adjacent_model_prices(self):
        html = "<section><div>" + self.row() + self.row("vendor/paid", ["0.1", "0.2", "-"]) + "</div></section>"
        self.assertEqual(len(free_text_rows(html)), 1)


if __name__ == "__main__":
    unittest.main()

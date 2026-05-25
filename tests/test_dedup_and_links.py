import unittest

from bank_adapters.models import canonical_operation, link_internal_transfers


class DedupAndLinksTest(unittest.TestCase):
    def test_duplicate_key_same_for_same_operation(self):
        kwargs = dict(
            profile_id="p",
            bank="Сбер",
            account_id="acc",
            operation_datetime="2026-05-01T10:00:00",
            description="Оплата",
            bank_amount=-100.0,
            auth_code="123456",
            card_last4="1111",
        )
        self.assertEqual(canonical_operation(**kwargs)["duplicate_key"], canonical_operation(**kwargs)["duplicate_key"])

    def test_link_internal_transfer_pair(self):
        out = canonical_operation(profile_id="p", id="out", bank="Сбер", operation_datetime="2026-05-01T10:00:00", description="Перевод в Яндекс кошелёк", bank_amount=-1000.0)
        inc = canonical_operation(profile_id="p", id="in", bank="Яндекс Банк", operation_datetime="2026-05-02T10:00:00", description="Пополнение кошелька Сбербанк", bank_amount=1000.0)
        pairs = link_internal_transfers("p", [out, inc])
        self.assertEqual(len(pairs), 1)


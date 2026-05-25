import unittest

from bank_adapters.models import apply_own_identity, canonical_operation, is_probable_own_transfer


class OwnIdentityTransfersTest(unittest.TestCase):
    def test_exact_name_and_phone(self):
        profile = {"own_identity": {"full_name": "Шутилин Никита Юрьевич", "name_aliases": ["Никита Юрьевич Ш."], "phones": ["+79001112233"], "account_last4": [], "banks": []}}
        op = canonical_operation(description="Входящий перевод СБП, Никита Юрьевич Ш., +79001112233, Сбербанк", bank_amount=1000)
        result = is_probable_own_transfer(op, profile)
        self.assertTrue(result["is_own_transfer"])
        self.assertGreaterEqual(result["confidence"], 0.95)
        self.assertFalse(apply_own_identity(op, profile)["needs_review"])

    def test_name_only_requires_review(self):
        profile = {"own_identity": {"full_name": "Шутилин Никита Юрьевич", "name_aliases": ["Ш. Никита Юрьевич"], "phones": [], "account_last4": [], "banks": []}}
        op = canonical_operation(description="Перевод от Ш. Никита Юрьевич", bank_amount=1000)
        updated = apply_own_identity(op, profile)
        self.assertEqual(updated["operation_type"], "Внутренний перевод")
        self.assertTrue(updated["needs_review"])

    def test_other_person_not_internal(self):
        profile = {"own_identity": {"full_name": "Шутилин Семен Юрьевич", "name_aliases": [], "phones": [], "account_last4": [], "banks": []}}
        op = canonical_operation(description="Перевод от Ш. Никита Юрьевич", bank_amount=1000)
        self.assertFalse(is_probable_own_transfer(op, profile)["is_own_transfer"])


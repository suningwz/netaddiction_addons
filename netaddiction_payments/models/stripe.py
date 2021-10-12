# Copyright 2021 Netaddiction s.r.l. (netaddiction.it)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
import stripe

from odoo import api, models, fields
from odoo.tools.float_utils import float_round


INT_CURRENCIES = [
    "BIF",
    "XAF",
    "XPF",
    "CLP",
    "KMF",
    "DJF",
    "GNF",
    "JPY",
    "MGA",
    "PYG",
    "RWF",
    "KRW",
    "VUV",
    "VND",
    "XOF",
]


class CardExist(Exception):
    def __init__(self, msg="Questa carta di credito è già associata al tuo account", *args, **kwargs):
        super(CardExist, self).__init__(msg, *args, **kwargs)


class StripeAcquirer(models.Model):
    _inherit = "payment.acquirer"

    provider = fields.Selection(
        selection_add=[("netaddiction_stripe", "Netaddiction Stripe")],
        ondelete={"netaddiction_stripe": "set default"},
    )
    netaddiction_stripe_pk = fields.Char(
        string="Chiave pubblica Stripe", required_if_provider="netaddiction_stripe", groups="base.group_user"
    )
    netaddiction_stripe_sk = fields.Char(
        string="Chiave privata Stripe", required_if_provider="netaddiction_stripe", groups="base.group_user"
    )

    def netaddiction_stripe_get_form_action_url(self):
        return "/netaddiction_stripe/payment/feedback"

    def get_or_create_customer(self, partner):
        stripe.api_key = self.sudo().netaddiction_stripe_sk
        customer = stripe.Customer.list(email=partner.email)
        if not customer:
            c_name = partner.name if partner.name else partner.id
            customer = stripe.Customer.create(name=c_name, email=partner.email)
            return customer["id"]
        else:
            return customer.data[0]["id"]

    def create_setup_intent(self, user):
        stripe.api_key = self.sudo().netaddiction_stripe_sk

        return stripe.SetupIntent.create(
            customer=self.get_or_create_customer(user.partner_id),
            payment_method="card_1JiiAjHprgG5j0TdTQlCr44O",
            payment_method_options={"card": {"request_three_d_secure": "any"}},
        )

    @api.model
    def get_payments_token(self, data):
        results = []
        for token in self.env["payment.token"].search(
            [("acquirer_id", "=", int(data["acquirer_id"])), ("partner_id", "=", int(data["partner_id"]))]
        ):
            results.append(
                {
                    "id": token.id,
                    "brand": token.brand,
                    "last4": token.name.strip("X"),
                    "isDefault": token.default_payment,
                }
            )
        return results

    @api.model
    def create_payment_token(self, data):
        stripe.api_key = self.sudo().netaddiction_stripe_sk
        res = stripe.PaymentMethod.retrieve(data.get("payment_method"))
        token = (
            self.env["payment.token"]
            .sudo()
            .search([("netaddiction_stripe_payment_method", "=", data.get("payment_method"))])
        )
        if token:
            return token
        card = res.get("card", {})
        if card:
            payment_token = (
                self.env["payment.token"]
                .sudo()
                .create(
                    {
                        "acquirer_id": int(data["acquirer_id"]),
                        "partner_id": int(data["partner_id"]),
                        "netaddiction_stripe_payment_method": data.get("payment_method"),
                        "name": f"XXXXXXXXXXXX{card.get('last4', '****')}",
                        "brand": card.get("brand", ""),
                        "acquirer_ref": self.get_or_create_customer(int(data["partner_id"])),
                        "active": False,
                    }
                )
            )
            return payment_token


class StripePaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def ns_do_transaction(self):
        self.ensure_one()
        result = self._ns_create_payment_intent()
        return self._ns_validate_response(result)

    def get_payment_from_order(self, order):
        for payment in order.transaction_ids:
            if payment.payment_id.state != "posted" and payment.acquirer_id.provider == "netaddiction_stripe":
                return payment

    def _ns_create_payment_intent(self):
        stripe.api_key = self.acquirer_id.sudo().netaddiction_stripe_sk
        res = stripe.PaymentIntent.create(
            amount=int(self.amount if self.currency_id.name in INT_CURRENCIES else float_round(self.amount * 100, 2)),
            currency="eur",
            off_session=True,
            confirm=True,
            payment_method=self.payment_token_id.netaddiction_stripe_payment_method,
            customer=self.payment_token_id.acquirer_ref,
            description=f"Ordine numero: {self.reference}",
        )
        if res.get("charges") and res.get("charges").get("total_count"):
            res = res.get("charges").get("data")[0]
        return res

    def _ns_validate_response(self, response):
        self.ensure_one()
        if self.state not in ("draft", "pending"):
            return True
        status = response.get("status")
        tx_id = response.get("id")
        vals = {
            "date": fields.datetime.now(),
            "acquirer_reference": tx_id,
        }
        if status == "succeeded":
            self.write(vals)
            self._set_transaction_done()
            return True
        if status in ("requires_action"):
            self.write(vals)
            self._set_transaction_error("Richiesta azione manuale")
            return False
        else:
            error = response.get("failure_message") or response.get("error", {}).get("message")
            self._set_transaction_error(error)
            return False


class StripePaymentToken(models.Model):
    _inherit = "payment.token"

    netaddiction_stripe_payment_method = fields.Char("Payment Method ID")
    default_payment = fields.Boolean("Carta predefinita ?", default=False)
    brand = fields.Char("Brand della carta")

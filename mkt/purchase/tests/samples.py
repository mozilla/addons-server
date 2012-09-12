import time


now = int(time.time()) - 10  # Just in case.
refund = {
    'iss' : 'tu.com',
    'aud' : 'developerIdentifier',
    'typ' : 'tu.com/payments/v1/refund',
    'exp' : now + 3600,
    'iat' : now,
    'request' : {
        'name' : 'Piece of Cake',
        'description' : 'Virtual chocolate cake to fill your virtual tummy',
        'price' : [{
            'currency': 'USD',
            'amount': '5.50'
        },
        {
            'currency': 'BRL',
            'amount': '11.07'
        }],
        'defaultPrice': 'USD',
        'productData': 'my_product_id=123',
        'postbackURL': 'http://developerserver.com/postback',
        'chargebackURL': 'http://developerserver.com/chargeback'
    },
    'response' : {
        'transactionID': '1',
        'reason': 'refund'
    }
}

non_existant_pay = {
    'request': {
        'productData': 'my_product_id=123&contrib_uuid=<bogus>'
    }
}

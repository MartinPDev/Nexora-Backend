import ccxt

from app.core.encryption import decrypt_value
from app.models.exchange_key import ExchangeKey


def build_exchange(exchange_key: ExchangeKey):
    print("RAW KEY:", exchange_key.api_key_encrypted)
    print("RAW SECRET:", exchange_key.api_secret_encrypted)

    exchange_name = exchange_key.exchange_name.lower()
    exchange_class = getattr(ccxt, exchange_name)

    config = {
        "apiKey": decrypt_value(exchange_key.api_key_encrypted),
        "secret": decrypt_value(exchange_key.api_secret_encrypted),
        "enableRateLimit": True,
    }

    if exchange_key.api_passphrase_encrypted:
        config["password"] = decrypt_value(exchange_key.api_passphrase_encrypted)

    exchange = exchange_class(config)
    return exchange

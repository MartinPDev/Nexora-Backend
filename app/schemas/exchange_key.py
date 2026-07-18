from pydantic import BaseModel


class ExchangeKeyCreate(BaseModel):
    exchange_name: str
    api_key: str
    api_secret: str
    api_passphrase: str | None = None
    is_testnet: bool = False
    label: str | None = None


class ExchangeKeyOut(BaseModel):
    id: str
    exchange_name: str
    is_testnet: bool
    label: str | None

    class Config:
        from_attributes = True

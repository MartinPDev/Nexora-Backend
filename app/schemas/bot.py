from pydantic import BaseModel


class BotCreate(BaseModel):
    name: str
    strategy_id: str
    exchange_key_id: str


class BotToggle(BaseModel):
    is_enabled: bool


class BotOut(BaseModel):
    id: str
    name: str
    strategy_id: str
    exchange_key_id: str
    status: str
    is_enabled: bool
    last_run_at: str | None = None
    last_error: str | None = None

    class Config:
        from_attributes = True

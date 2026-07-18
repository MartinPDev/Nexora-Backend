from pydantic import BaseModel


class StrategyCreate(BaseModel):
    name: str
    symbol: str
    timeframe: str
    risk_percent: float
    take_profit_percent: float | None = None
    stop_loss_percent: float | None = None
    is_ai_enabled: bool = True
    config_json: dict = {}


class StrategyOut(BaseModel):
    id: str
    name: str
    symbol: str
    timeframe: str
    risk_percent: float
    take_profit_percent: float | None = None
    stop_loss_percent: float | None = None
    is_ai_enabled: bool
    config_json: dict

    class Config:
        from_attributes = True

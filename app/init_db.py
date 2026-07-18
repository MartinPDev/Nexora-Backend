from app.core.database import engine, Base
from app.models import user, exchange_key, strategy, bot, rapid_scalper_trade
print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Done.")

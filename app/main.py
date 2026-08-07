from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings as app_settings
from app.database import get_supabase
from app.routers import (
    activity_log,
    analytics,
    auth,
    bank_accounts,
    delivery_challans,
    expenses,
    inbox,
    internal,
    inventory,
    invoices,
    login_approvals,
    master_data,
    notification_preferences,
    parties,
    purchases,
    settings,
    users,
)
from app.services import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    if app_settings.enable_scheduler:
        scheduler.start_scheduler(get_supabase())
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(title="Omega Scales Backend", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(login_approvals.router)
app.include_router(settings.router)
app.include_router(internal.router)
app.include_router(inbox.router)
app.include_router(analytics.router)
app.include_router(inventory.router)
app.include_router(master_data.router)
app.include_router(parties.router)
app.include_router(invoices.router)
app.include_router(purchases.router)
app.include_router(expenses.router)
app.include_router(notification_preferences.router)
app.include_router(bank_accounts.router)
app.include_router(activity_log.router)
app.include_router(delivery_challans.router)


@app.get("/health")
def health():
    return {"status": "ok"}

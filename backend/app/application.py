from .forecast_api import router as analytics_router
from .main import app

app.include_router(analytics_router)

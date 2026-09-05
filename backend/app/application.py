from .forecast_api import router as analytics_router
from .main import app
from .version import APP_VERSION

app.version = APP_VERSION
app.include_router(analytics_router)

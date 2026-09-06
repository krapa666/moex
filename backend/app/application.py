from .canary_evidence_api import router as canary_evidence_router
from .consensus_canary_api import router as consensus_canary_router
from .consensus_robustness_api import router as consensus_robustness_router
from .forecast_api import router as analytics_router
from .main import app
from .production_impact_api import router as production_impact_router
from .shadow_consensus_api import router as shadow_consensus_router
from .version import APP_VERSION

app.version = APP_VERSION
app.include_router(analytics_router)
app.include_router(consensus_robustness_router)
app.include_router(shadow_consensus_router)
app.include_router(production_impact_router)
app.include_router(consensus_canary_router)
app.include_router(canary_evidence_router)

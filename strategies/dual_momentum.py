from .base import BaseStrategy
import settings


class DualMomentumStrategy(BaseStrategy):
    """듀얼 모멘텀 전략 — 파라미터: settings.yaml → params.dual_momentum"""

    def __init__(self):
        super().__init__()
        p = settings.get_params("dual_momentum")
        self.STOP_LOSS = p.get("stop_loss", -5.0)

    def get_targets(self) -> list:
        return settings.STOCK_CODES

    def should_buy(self, data: dict) -> bool:
        return data["change_pct"] > 0

    def should_sell(self, data: dict, holding: dict) -> bool:
        avg = float(holding.get("pchs_avg_pric", 0))
        pct = (data["current"] - avg) / avg * 100 if avg else 0
        return data["change_pct"] < 0 or pct <= self.STOP_LOSS

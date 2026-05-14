from .base import BaseStrategy
import settings


class MomentumStrategy(BaseStrategy):
    """52주 신고가 모멘텀 전략 — 파라미터: settings.yaml → params.momentum"""

    def __init__(self):
        super().__init__()
        p = settings.get_params("momentum")
        self.TAKE_PROFIT = p.get("take_profit",  5.0)
        self.STOP_LOSS   = p.get("stop_loss",   -3.0)

    def get_targets(self) -> list:
        return settings.STOCK_CODES

    def should_buy(self, data: dict) -> bool:
        return data["current"] >= data["high_52w"]

    def should_sell(self, data: dict, holding: dict) -> bool:
        avg   = float(holding.get("pchs_avg_pric", 0))
        pct   = (data["current"] - avg) / avg * 100 if avg else 0
        return pct >= self.TAKE_PROFIT or pct <= self.STOP_LOSS

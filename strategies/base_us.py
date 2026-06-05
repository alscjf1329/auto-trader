from abc import ABC, abstractmethod


class BaseStrategyUS(ABC):
    """미국주식 전략 베이스 클래스"""

    def __init__(self):
        pass

    @abstractmethod
    def get_targets(self) -> list[str]:
        """매매 대상 티커 리스트 (예: ['AAPL', 'NVDA'])"""
        pass

    @abstractmethod
    def should_buy(self, data: dict) -> bool:
        """매수 조건 — True 반환 시 매수"""
        pass

    @abstractmethod
    def should_sell(self, data: dict, holding: dict) -> bool:
        """매도 조건 — True 반환 시 매도"""
        pass

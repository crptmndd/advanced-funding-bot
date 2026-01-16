"""
OKX Trading Client.

Клиент для работы с OKX API v5 через REST API.
Поддерживает торговлю фьючерсами (SWAP) с изолированной и кросс-маржой.
"""

import hmac
import hashlib
import base64
import json
import time
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class OKXOrderResult:
    """Result of an OKX order operation."""
    success: bool
    order_id: Optional[str] = None
    algo_id: Optional[str] = None
    status: Optional[str] = None
    filled_size: float = 0.0
    average_price: Optional[float] = None
    error: Optional[str] = None
    raw_response: Optional[Dict] = None


@dataclass
class OKXPosition:
    """Represents an OKX trading position."""
    symbol: str
    inst_id: str
    size: float  # Positive = long, negative = short
    pos_side: str  # "long", "short", or "net"
    entry_price: float
    mark_price: float
    liquidation_price: Optional[float]
    unrealized_pnl: float
    margin: float
    leverage: int
    margin_mode: str  # "cross" or "isolated"


@dataclass
class OKXAccountState:
    """OKX account state information."""
    total_equity: float
    available_balance: float
    margin_used: float
    positions: List[OKXPosition]


class OKXClient:
    """Клиент для работы с OKX API v5 через REST API (async)"""
    
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        sandbox: bool = False,
        log_tag: Optional[str] = None,
    ):
        """
        Инициализация клиента OKX
        
        Args:
            api_key: API ключ
            secret_key: Секретный ключ
            passphrase: Парольная фраза
            sandbox: Использовать тестовую среду
            log_tag: Тэг для логов
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.sandbox = sandbox
        self.log_tag = log_tag
        
        self.base_url = "https://www.okx.com"
        
        # Кеш для instrument_id
        self._instrument_id_cache: Dict[str, str] = {}
        
        # Кеш для account/config
        self._account_config_cache: Optional[Dict] = None
        self._account_config_cache_ts: float = 0.0
        self._account_config_cache_ttl_sec: int = 300
        
        logger.debug(f"{self._ctx()}OKX клиент инициализирован (sandbox={sandbox})")

    def _ctx(self) -> str:
        """Префикс для логов."""
        return f"[{self.log_tag}] " if self.log_tag else "[OKX] "
    
    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """Генерация подписи для аутентификации"""
        message = timestamp + method + request_path + body
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'),
            bytes(message, encoding='utf8'),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """Получение заголовков для запроса"""
        now = datetime.utcnow()
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        method_upper = method.upper()
        signature = self._generate_signature(timestamp, method_upper, request_path, body)
        
        return {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict] = None, 
        data: Optional[Dict] = None,
        timeout: float = 10.0,
    ) -> Optional[List[Dict]]:
        """Выполнение HTTP запроса к OKX API"""
        url = f"{self.base_url}{endpoint}"
        body = ""
        
        if data:
            body = json.dumps(data)
        
        request_path = endpoint
        if method == "GET" and params:
            sorted_params = sorted(params.items())
            query_string = "&".join([f"{k}={v}" for k, v in sorted_params])
            request_path = f"{endpoint}?{query_string}"
            params = sorted_params
        
        headers = self._get_headers(method, request_path, body)
        ctx = self._ctx()
        
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        return await self._handle_response(resp, ctx, method, request_path)
                elif method == "POST":
                    async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        return await self._handle_response(resp, ctx, method, request_path)
                elif method == "DELETE":
                    async with session.delete(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        return await self._handle_response(resp, ctx, method, request_path)
                else:
                    logger.error(f"{ctx}Неподдерживаемый HTTP метод: {method}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error(f"{ctx}Timeout при запросе к OKX API: {method} {endpoint}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"{ctx}Ошибка HTTP клиента: {e}")
            return None
        except Exception as e:
            logger.error(f"{ctx}Неожиданная ошибка при запросе к OKX API: {e}", exc_info=True)
            return None
    
    async def _handle_response(self, resp: aiohttp.ClientResponse, ctx: str, method: str, request_path: str) -> Optional[List[Dict]]:
        """Handle API response"""
        try:
            result = await resp.json()
        except json.JSONDecodeError as e:
            logger.error(f"{ctx}Ошибка парсинга JSON ответа: {e}")
            return None
        
        if result.get('code') == '0':
            data = result.get('data', [])
            return data if isinstance(data, list) else [data] if data else []
        else:
            error_msg = result.get('msg', 'Unknown error')
            error_code = result.get('code', 'Unknown')
            
            s_code = None
            s_msg = None
            try:
                d = result.get("data", [])
                if isinstance(d, list) and d:
                    d0 = d[0]
                    if isinstance(d0, dict):
                        s_code = d0.get("sCode")
                        s_msg = d0.get("sMsg")
            except Exception:
                pass
            
            extra = f", sCode={s_code}, sMsg={s_msg}" if (s_code or s_msg) else ""
            logger.error(f"{ctx}Ошибка API OKX [{method} {request_path}]: {error_msg} (code: {error_code}{extra})")
            return None

    async def get_account_config(self, use_cache: bool = True) -> Optional[Dict]:
        """Получить конфиг аккаунта"""
        now = time.time()
        if (
            use_cache
            and self._account_config_cache is not None
            and (now - self._account_config_cache_ts) < self._account_config_cache_ttl_sec
        ):
            return self._account_config_cache

        res = await self._request("GET", "/api/v5/account/config", params={})
        if not res or not isinstance(res, list):
            logger.warning(f"{self._ctx()}Не удалось получить account/config")
            return None
        
        cfg = res[0] if res else None
        if not isinstance(cfg, dict):
            return None

        self._account_config_cache = cfg
        self._account_config_cache_ts = now
        return cfg

    async def get_position_mode(self) -> Optional[str]:
        """Вернуть режим позиций: 'net_mode' или 'long_short_mode'"""
        cfg = await self.get_account_config(use_cache=True)
        if not cfg:
            return None
        return str(cfg.get("posMode")) if cfg.get("posMode") else None
    
    async def get_instrument_id(self, ticker: str, use_cache: bool = True) -> Optional[str]:
        """Получение instrument ID для тикера"""
        ticker = ticker.replace('$', '').strip().upper()
        
        if use_cache and ticker in self._instrument_id_cache:
            return self._instrument_id_cache[ticker]
        
        # Нормализуем тикер
        if '-' in ticker:
            base_quote = ticker
        else:
            # BTCUSDT -> BTC-USDT
            if ticker.endswith('USDT'):
                base_quote = f"{ticker[:-4]}-USDT"
            elif ticker.endswith('USD'):
                base_quote = f"{ticker[:-3]}-USD"
            else:
                base_quote = f"{ticker}-USDT"
        
        # Пробуем SWAP формат
        inst_id = f"{base_quote}-SWAP"
        
        result = await self._request("GET", "/api/v5/public/instruments", params={"instType": "SWAP", "instId": inst_id})
        
        if result and len(result) > 0:
            found_id = result[0].get('instId')
            if found_id:
                self._instrument_id_cache[ticker] = found_id
                logger.info(f"{self._ctx()}Найден instrument ID: {found_id} для тикера {ticker}")
                return found_id
        
        logger.error(f"{self._ctx()}Не удалось найти instrument ID для тикера {ticker}")
        return None
    
    async def get_instrument_info(self, instrument_id: str) -> Optional[Dict]:
        """Получение информации об инструменте"""
        inst_type = 'SWAP' if '-SWAP' in instrument_id.upper() else 'SPOT'
        
        result = await self._request("GET", "/api/v5/public/instruments", params={"instType": inst_type, "instId": instrument_id})
        
        if result and len(result) > 0:
            return result[0]
        return None
    
    async def set_leverage(self, instrument_id: str, leverage: int, margin_mode: str = "isolated") -> bool:
        """Установка плеча для инструмента"""
        endpoint = "/api/v5/account/set-leverage"
        pos_mode = await self.get_position_mode()
        
        # Сначала пробуем без posSide
        if pos_mode != "long_short_mode":
            data = {
                "instId": instrument_id,
                "lever": str(leverage),
                "mgnMode": margin_mode
            }
            result = await self._request("POST", endpoint, data=data)
            if result:
                try:
                    s_code = str(result[0].get("sCode", "0"))
                    if s_code == "0":
                        logger.debug(f"{self._ctx()}Плечо {leverage}x установлено для {instrument_id}")
                        return True
                except Exception:
                    return True
        
        # Фоллбек: пробуем для обеих сторон
        success_any = False
        for pos_side in ["long", "short"]:
            data = {
                "instId": instrument_id,
                "lever": str(leverage),
                "mgnMode": margin_mode,
                "posSide": pos_side
            }
            res = await self._request("POST", endpoint, data=data)
            if res:
                try:
                    s_code = str(res[0].get("sCode", "0"))
                    if s_code == "0":
                        success_any = True
                except Exception:
                    success_any = True
        
        return success_any
    
    async def get_last_price(self, instrument_id: str) -> Optional[float]:
        """Получить текущую цену инструмента"""
        result = await self._request("GET", "/api/v5/market/ticker", params={"instId": instrument_id})
        if result and len(result) > 0:
            try:
                return float(result[0].get("last", "0"))
            except Exception:
                return None
        return None
    
    def calculate_position_size(
        self, 
        margin_amount: float, 
        entry_price: float, 
        leverage: int, 
        instrument_info: Dict,
    ) -> float:
        """Расчет размера позиции в контрактах"""
        ct_val = float(instrument_info.get('ctVal', '0.01'))
        lot_sz = float(instrument_info.get('lotSz', '1'))
        
        # Стоимость позиции = маржа × плечо
        position_value_usdt = margin_amount * leverage
        
        # Для USDT-margined: размер = стоимость / (цена × ctVal)
        ct_type = instrument_info.get('ctType', '')
        if ct_type == 'linear' or 'USDT' in instrument_info.get('instId', ''):
            position_size = position_value_usdt / (entry_price * ct_val)
        else:
            position_size = position_value_usdt / entry_price
        
        # Округляем до lotSz
        if lot_sz > 0:
            position_size = round(position_size / lot_sz) * lot_sz
        
        return position_size
    
    async def place_market_order(
        self,
        instrument_id: str,
        side: str,
        size: float,
        margin_mode: str = "isolated",
        reduce_only: bool = False,
        position_side: Optional[str] = None,
        leverage: Optional[int] = None,
    ) -> OKXOrderResult:
        """Размещение рыночного ордера"""
        ctx = self._ctx()
        
        if size <= 0:
            return OKXOrderResult(success=False, error="Invalid size")
        
        # Устанавливаем плечо если указано
        if leverage and not reduce_only:
            await self.set_leverage(instrument_id, leverage, margin_mode)
        
        # Форматируем размер
        instrument_info = await self.get_instrument_info(instrument_id)
        if instrument_info:
            lot_sz = float(instrument_info.get("lotSz", "1"))
            if lot_sz >= 1:
                size_str = str(int(round(size)))
            else:
                size_decimals = len(str(lot_sz).split(".")[-1].rstrip("0"))
                size_str = f"{size:.{size_decimals}f}".rstrip("0").rstrip(".")
        else:
            size_str = str(int(size)) if size == int(size) else f"{size:.8f}".rstrip("0").rstrip(".")
        
        pos_mode = await self.get_position_mode()
        
        endpoint = "/api/v5/trade/order"
        data: Dict[str, Any] = {
            "instId": instrument_id,
            "tdMode": margin_mode,
            "side": side,
            "ordType": "market",
            "sz": size_str,
        }
        
        if reduce_only:
            data["reduceOnly"] = "true"
        
        if pos_mode == "long_short_mode" and position_side:
            data["posSide"] = position_side
        
        logger.debug(f"{ctx}Размещение маркет ордера: {data}")
        result = await self._request("POST", endpoint, data=data)
        
        if result and len(result) > 0:
            order_data = result[0]
            s_code = order_data.get("sCode")
            if s_code is None or str(s_code) == "0":
                return OKXOrderResult(
                    success=True,
                    order_id=order_data.get("ordId"),
                    status="submitted",
                    raw_response=order_data,
                )
            else:
                return OKXOrderResult(
                    success=False,
                    error=f"sCode={s_code}, sMsg={order_data.get('sMsg')}",
                    raw_response=order_data,
                )
        
        return OKXOrderResult(success=False, error="No response from API")
    
    async def place_limit_order(
        self,
        instrument_id: str,
        side: str,
        price: float,
        size: float,
        leverage: int,
        margin_mode: str = "isolated",
        position_side: Optional[str] = None,
    ) -> OKXOrderResult:
        """Размещение лимитного ордера"""
        ctx = self._ctx()
        
        if size <= 0:
            return OKXOrderResult(success=False, error="Invalid size")
        
        # Устанавливаем плечо
        await self.set_leverage(instrument_id, leverage, margin_mode)
        
        # Форматируем размер и цену
        instrument_info = await self.get_instrument_info(instrument_id)
        if instrument_info:
            lot_sz = float(instrument_info.get('lotSz', '1'))
            tick_sz = float(instrument_info.get('tickSz', '0.0001'))
            
            if lot_sz >= 1:
                size_str = str(int(size))
            else:
                size_decimals = len(str(lot_sz).split('.')[-1].rstrip('0'))
                size_str = f"{size:.{size_decimals}f}".rstrip('0').rstrip('.')
            
            if tick_sz >= 1:
                price_str = str(int(price))
            else:
                price_decimals = len(str(tick_sz).split('.')[-1].rstrip('0'))
                price_str = f"{price:.{price_decimals}f}".rstrip('0').rstrip('.')
        else:
            size_str = str(int(size)) if size == int(size) else f"{size:.8f}".rstrip('0').rstrip('.')
            price_str = f"{price:.4f}".rstrip('0').rstrip('.')
        
        pos_mode = await self.get_position_mode()
        
        endpoint = "/api/v5/trade/order"
        data: Dict[str, Any] = {
            "instId": instrument_id,
            "tdMode": margin_mode,
            "side": side,
            "ordType": "limit",
            "sz": size_str,
            "px": price_str,
        }
        
        if pos_mode == "long_short_mode" and position_side:
            data["posSide"] = position_side
        
        logger.debug(f"{ctx}Размещение лимитного ордера: {data}")
        result = await self._request("POST", endpoint, data=data)
        
        if result and len(result) > 0:
            order_data = result[0]
            s_code = order_data.get("sCode")
            if s_code is None or str(s_code) == "0":
                return OKXOrderResult(
                    success=True,
                    order_id=order_data.get("ordId"),
                    status="submitted",
                    raw_response=order_data,
                )
            else:
                return OKXOrderResult(
                    success=False,
                    error=f"sCode={s_code}, sMsg={order_data.get('sMsg')}",
                    raw_response=order_data,
                )
        
        return OKXOrderResult(success=False, error="No response from API")
    
    async def get_positions(self, instrument_id: Optional[str] = None) -> List[OKXPosition]:
        """Получить текущие позиции"""
        params: Dict[str, str] = {}
        if instrument_id:
            params["instId"] = instrument_id
        
        result = await self._request("GET", "/api/v5/account/positions", params=params)
        
        positions = []
        if result:
            for p in result:
                pos_val = float(p.get("pos", "0"))
                if pos_val == 0:
                    continue
                
                positions.append(OKXPosition(
                    symbol=p.get("instId", "").replace("-SWAP", "").replace("-USDT", ""),
                    inst_id=p.get("instId", ""),
                    size=pos_val,
                    pos_side=p.get("posSide", "net"),
                    entry_price=float(p.get("avgPx", "0") or "0"),
                    mark_price=float(p.get("markPx", "0") or "0"),
                    liquidation_price=float(p.get("liqPx", "0") or "0") if p.get("liqPx") else None,
                    unrealized_pnl=float(p.get("upl", "0") or "0"),
                    margin=float(p.get("margin", "0") or "0"),
                    leverage=int(float(p.get("lever", "1") or "1")),
                    margin_mode=p.get("mgnMode", "isolated"),
                ))
        
        return positions
    
    async def get_open_orders(self, instrument_id: Optional[str] = None) -> List[Dict]:
        """Получить открытые ордера"""
        params: Dict[str, str] = {"instType": "SWAP"}
        if instrument_id:
            params["instId"] = instrument_id
        
        result = await self._request("GET", "/api/v5/trade/orders-pending", params=params)
        return result if result else []
    
    async def cancel_order(self, instrument_id: str, order_id: str) -> bool:
        """Отменить ордер"""
        data = {"instId": instrument_id, "ordId": order_id}
        result = await self._request("POST", "/api/v5/trade/cancel-order", data=data)
        
        if not result or len(result) == 0:
            return False
        
        try:
            return str(result[0].get("sCode", "")) == "0"
        except Exception:
            return True
    
    async def close_position(
        self, 
        instrument_id: str, 
        pos_side: Optional[str] = None, 
        margin_mode: str = "isolated",
    ) -> bool:
        """Закрыть позицию"""
        ctx = self._ctx()
        
        pos_mode = await self.get_position_mode()
        logger.debug(f"{ctx}close_position: posMode={pos_mode}, requested pos_side={pos_side}")
        
        effective_pos_side = pos_side
        if pos_mode == "net_mode":
            effective_pos_side = "net"
        
        data: Dict[str, str] = {"instId": instrument_id, "mgnMode": margin_mode}
        if effective_pos_side:
            data["posSide"] = effective_pos_side
        
        logger.debug(f"{ctx}close_position payload: {data}")
        result = await self._request("POST", "/api/v5/trade/close-position", data=data)
        
        # If _request returns data, API call was successful (code == "0" already checked)
        # For close-position endpoint, items in data don't have sCode, they have instId/posSide
        if result and len(result) > 0:
            logger.info(f"{ctx}Position closed successfully for {instrument_id}")
            return True
        
        # Фоллбек: market order
        logger.debug(f"{ctx}close_position: пробуем market order")
        positions = await self.get_positions(instrument_id)
        
        for p in positions:
            if p.inst_id != instrument_id:
                continue
            if pos_side and p.pos_side != pos_side and p.pos_side != "net":
                continue
            
            pos_sz = abs(p.size)
            if pos_sz <= 0:
                continue
            
            side = "sell" if p.size > 0 else "buy"
            fallback_pos_side = p.pos_side if p.pos_side != "net" else None
            
            order_result = await self.place_market_order(
                instrument_id=instrument_id,
                side=side,
                size=pos_sz,
                margin_mode=margin_mode,
                reduce_only=True,
                position_side=fallback_pos_side,
            )
            if order_result.success:
                return True
        
        return False
    
    async def get_account_balance(self, currency: str = "USDT") -> Optional[Dict]:
        """Получить баланс аккаунта"""
        ctx = self._ctx()
        
        result = await self._request("GET", "/api/v5/account/balance", params={"ccy": currency})
        
        if not result or len(result) == 0:
            return None
        
        try:
            account_data = result[0]
            details = account_data.get("details", [])
            
            for detail in details:
                if detail.get("ccy") == currency:
                    available = float(detail.get("availBal") or detail.get("availEq") or "0")
                    equity = float(detail.get("eq") or detail.get("eqUsd") or "0")
                    total = float(detail.get("cashBal") or "0")
                    
                    return {
                        "available": available,
                        "equity": equity,
                        "total": total,
                    }
            
            total_eq = float(account_data.get("totalEq") or "0")
            if total_eq > 0:
                return {
                    "available": total_eq,
                    "equity": total_eq,
                    "total": total_eq,
                }
            
            return None
            
        except Exception as e:
            logger.error(f"{ctx}Ошибка парсинга баланса: {e}")
            return None
    
    async def get_account_state(self) -> Optional[OKXAccountState]:
        """Получить полное состояние аккаунта"""
        balance = await self.get_account_balance()
        if not balance:
            return None
        
        positions = await self.get_positions()
        
        return OKXAccountState(
            total_equity=balance.get("equity", 0),
            available_balance=balance.get("available", 0),
            margin_used=sum(p.margin for p in positions),
            positions=positions,
        )


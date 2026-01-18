"""
Withdrawal Transaction Tracker Service.

Monitors withdrawal transactions on Arbitrum and notifies users when confirmed.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Callable, Awaitable
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)

# Arbitrum RPC endpoints
ARBITRUM_RPC_URL = "https://arb1.arbitrum.io/rpc"

# USDC contracts on Arbitrum
USDC_CONTRACT = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # Native USDC
USDC_E_CONTRACT = "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"  # Bridged USDC.e

# ERC-20 Transfer event signature: Transfer(address,address,uint256)
TRANSFER_EVENT_SIGNATURE = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class TransactionStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class WithdrawalInfo:
    """Information about a pending withdrawal."""
    user_id: int
    telegram_user_id: int
    amount_usd: float
    wallet_address: str
    tx_hash: Optional[str] = None
    initiated_at: datetime = None
    status: TransactionStatus = TransactionStatus.PENDING
    confirmations: int = 0
    block_number: Optional[int] = None
    
    def __post_init__(self):
        if self.initiated_at is None:
            self.initiated_at = datetime.utcnow()


class WithdrawalTracker:
    """
    Service to track withdrawal transactions on Arbitrum.
    
    Monitors transactions and calls notification callback when confirmed.
    """
    
    def __init__(
        self,
        notification_callback: Optional[Callable[[WithdrawalInfo, str], Awaitable[None]]] = None,
        check_interval: int = 15,  # seconds
        max_tracking_time: int = 900,  # 15 minutes
        required_confirmations: int = 1,
    ):
        """
        Initialize the tracker.
        
        Args:
            notification_callback: Async function to call when withdrawal is confirmed
                                   Signature: async def callback(withdrawal_info, message)
            check_interval: How often to check transaction status (seconds)
            max_tracking_time: Maximum time to track a transaction (seconds)
            required_confirmations: Number of confirmations required
        """
        self._pending_withdrawals: Dict[str, WithdrawalInfo] = {}
        self._tracking_tasks: Dict[str, asyncio.Task] = {}
        self._notification_callback = notification_callback
        self._check_interval = check_interval
        self._max_tracking_time = max_tracking_time
        self._required_confirmations = required_confirmations
        
        logger.info("[Withdrawal Tracker] Initialized")
    
    def set_notification_callback(
        self, 
        callback: Callable[[WithdrawalInfo, str], Awaitable[None]]
    ) -> None:
        """Set the notification callback."""
        self._notification_callback = callback
    
    async def track_withdrawal(
        self,
        user_id: int,
        telegram_user_id: int,
        amount_usd: float,
        wallet_address: str,
        tx_hash: Optional[str] = None,
    ) -> WithdrawalInfo:
        """
        Start tracking a withdrawal transaction.
        
        Args:
            user_id: Database user ID
            telegram_user_id: Telegram user ID for notifications
            amount_usd: Amount withdrawn in USD
            wallet_address: Destination wallet address
            tx_hash: Transaction hash (if known)
            
        Returns:
            WithdrawalInfo object
        """
        withdrawal = WithdrawalInfo(
            user_id=user_id,
            telegram_user_id=telegram_user_id,
            amount_usd=amount_usd,
            wallet_address=wallet_address,
            tx_hash=tx_hash,
        )
        
        # Generate tracking key
        tracking_key = f"{telegram_user_id}_{withdrawal.initiated_at.timestamp()}"
        
        self._pending_withdrawals[tracking_key] = withdrawal
        
        # Start tracking task
        task = asyncio.create_task(
            self._track_withdrawal_task(tracking_key, withdrawal)
        )
        self._tracking_tasks[tracking_key] = task
        
        logger.info(
            f"[Withdrawal Tracker] Started tracking withdrawal for user {telegram_user_id}: "
            f"${amount_usd} to {wallet_address[:10]}..."
        )
        
        return withdrawal
    
    async def _track_withdrawal_task(
        self,
        tracking_key: str,
        withdrawal: WithdrawalInfo,
    ) -> None:
        """Background task to track a withdrawal."""
        start_time = datetime.utcnow()
        max_time = timedelta(seconds=self._max_tracking_time)
        check_count = 0
        
        logger.info(f"[Withdrawal Tracker] Tracking task started for {tracking_key}")
        logger.info(f"[Withdrawal Tracker] Wallet: {withdrawal.wallet_address}, Amount: ${withdrawal.amount_usd}")
        
        try:
            while datetime.utcnow() - start_time < max_time:
                check_count += 1
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                
                logger.debug(
                    f"[Withdrawal Tracker] Check #{check_count} for {tracking_key[:20]}... "
                    f"(elapsed: {elapsed:.0f}s)"
                )
                
                # If we don't have tx_hash, try to find it
                if not withdrawal.tx_hash:
                    tx_hash = await self._find_withdrawal_tx(
                        withdrawal.wallet_address,
                        withdrawal.amount_usd,
                        withdrawal.initiated_at,
                    )
                    if tx_hash:
                        withdrawal.tx_hash = tx_hash
                        logger.info(f"[Withdrawal Tracker] ✅ Found tx hash: {tx_hash}")
                
                # Check transaction status if we have hash
                if withdrawal.tx_hash:
                    status, confirmations, block = await self._check_transaction_status(
                        withdrawal.tx_hash
                    )
                    
                    withdrawal.confirmations = confirmations
                    withdrawal.block_number = block
                    
                    logger.debug(
                        f"[Withdrawal Tracker] Tx status: {status}, confirmations: {confirmations}"
                    )
                    
                    if status == "confirmed" and confirmations >= self._required_confirmations:
                        withdrawal.status = TransactionStatus.CONFIRMED
                        logger.info(f"[Withdrawal Tracker] ✅ Transaction confirmed with {confirmations} confirmations")
                        await self._notify_confirmed(withdrawal)
                        break
                    elif status == "failed":
                        withdrawal.status = TransactionStatus.FAILED
                        logger.warning(f"[Withdrawal Tracker] ❌ Transaction failed")
                        await self._notify_failed(withdrawal)
                        break
                
                # Wait before next check
                await asyncio.sleep(self._check_interval)
            
            else:
                # Timeout reached
                if withdrawal.status == TransactionStatus.PENDING:
                    withdrawal.status = TransactionStatus.TIMEOUT
                    logger.warning(
                        f"[Withdrawal Tracker] ⏰ Timeout after {self._max_tracking_time}s, "
                        f"tx_hash found: {withdrawal.tx_hash is not None}"
                    )
                    await self._notify_timeout(withdrawal)
        
        except asyncio.CancelledError:
            logger.info(f"[Withdrawal Tracker] Tracking cancelled for {tracking_key}")
        except Exception as e:
            logger.exception(f"[Withdrawal Tracker] Error tracking {tracking_key}: {e}")
        finally:
            # Cleanup
            self._pending_withdrawals.pop(tracking_key, None)
            self._tracking_tasks.pop(tracking_key, None)
    
    async def _check_transaction_status(
        self,
        tx_hash: str,
    ) -> tuple[str, int, Optional[int]]:
        """
        Check transaction status on Arbitrum.
        
        Returns:
            Tuple of (status, confirmations, block_number)
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Get transaction receipt
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getTransactionReceipt",
                    "params": [tx_hash],
                    "id": 1,
                }
                
                async with session.post(ARBITRUM_RPC_URL, json=payload) as resp:
                    if resp.status != 200:
                        return "pending", 0, None
                    
                    data = await resp.json()
                    result = data.get("result")
                    
                    if not result:
                        return "pending", 0, None
                    
                    # Check status (1 = success, 0 = failed)
                    status_hex = result.get("status", "0x1")
                    status_int = int(status_hex, 16)
                    
                    if status_int == 0:
                        return "failed", 0, None
                    
                    block_number_hex = result.get("blockNumber")
                    if not block_number_hex:
                        return "pending", 0, None
                    
                    block_number = int(block_number_hex, 16)
                    
                    # Get current block number for confirmations
                    payload_block = {
                        "jsonrpc": "2.0",
                        "method": "eth_blockNumber",
                        "params": [],
                        "id": 2,
                    }
                    
                    async with session.post(ARBITRUM_RPC_URL, json=payload_block) as resp_block:
                        if resp_block.status == 200:
                            block_data = await resp_block.json()
                            current_block = int(block_data.get("result", "0x0"), 16)
                            confirmations = max(0, current_block - block_number + 1)
                        else:
                            confirmations = 1
                    
                    return "confirmed", confirmations, block_number
        
        except Exception as e:
            logger.error(f"[Withdrawal Tracker] Error checking tx status: {e}")
            return "pending", 0, None
    
    async def _find_withdrawal_tx(
        self,
        wallet_address: str,
        amount_usd: float,
        initiated_at: datetime,
    ) -> Optional[str]:
        """
        Try to find withdrawal transaction by scanning recent USDC transfers via RPC.
        
        Uses eth_getLogs to find ERC-20 Transfer events to the wallet.
        HyperLiquid withdrawals appear as USDC token transfers to the wallet.
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Get current block number
                payload_block = {
                    "jsonrpc": "2.0",
                    "method": "eth_blockNumber",
                    "params": [],
                    "id": 1,
                }
                
                async with session.post(ARBITRUM_RPC_URL, json=payload_block) as resp:
                    if resp.status != 200:
                        logger.warning(f"[Withdrawal Tracker] RPC error getting block number")
                        return None
                    
                    block_data = await resp.json()
                    current_block = int(block_data.get("result", "0x0"), 16)
                
                # Search last ~1000 blocks (~4 minutes on Arbitrum at ~0.25s per block)
                from_block = hex(max(0, current_block - 1000))
                
                # Pad wallet address to 32 bytes for topics filter
                wallet_padded = "0x" + wallet_address[2:].lower().zfill(64)
                
                logger.debug(f"[Withdrawal Tracker] Searching for USDC transfers to {wallet_address[:10]}...")
                logger.debug(f"[Withdrawal Tracker] Block range: {from_block} to {hex(current_block)}")
                
                # Check both USDC and USDC.e contracts
                for usdc_contract in [USDC_CONTRACT, USDC_E_CONTRACT]:
                    # Get Transfer event logs where topic2 (to) is our wallet
                    payload_logs = {
                        "jsonrpc": "2.0",
                        "method": "eth_getLogs",
                        "params": [{
                            "fromBlock": from_block,
                            "toBlock": "latest",
                            "address": usdc_contract,
                            "topics": [
                                TRANSFER_EVENT_SIGNATURE,  # Transfer event
                                None,  # from (any)
                                wallet_padded,  # to (our wallet)
                            ]
                        }],
                        "id": 2,
                    }
                    
                    async with session.post(ARBITRUM_RPC_URL, json=payload_logs) as resp:
                        if resp.status != 200:
                            continue
                        
                        logs_data = await resp.json()
                        logs = logs_data.get("result", [])
                        
                        if not logs:
                            continue
                        
                        logger.debug(f"[Withdrawal Tracker] Found {len(logs)} Transfer events from {usdc_contract[:10]}...")
                        
                        for log in logs:
                            # Get transaction hash
                            tx_hash = log.get("transactionHash")
                            if not tx_hash:
                                continue
                            
                            # Get block number and timestamp
                            block_hex = log.get("blockNumber")
                            if not block_hex:
                                continue
                            
                            block_num = int(block_hex, 16)
                            
                            # Get block timestamp
                            payload_block_info = {
                                "jsonrpc": "2.0",
                                "method": "eth_getBlockByNumber",
                                "params": [block_hex, False],
                                "id": 3,
                            }
                            
                            async with session.post(ARBITRUM_RPC_URL, json=payload_block_info) as block_resp:
                                if block_resp.status != 200:
                                    continue
                                
                                block_info = await block_resp.json()
                                block_result = block_info.get("result", {})
                                timestamp_hex = block_result.get("timestamp", "0x0")
                                block_timestamp = int(timestamp_hex, 16)
                                tx_time = datetime.utcfromtimestamp(block_timestamp)
                            
                            # Check time window: transaction must be after withdrawal initiation
                            time_diff = (tx_time - initiated_at).total_seconds()
                            
                            if time_diff < -60 or time_diff > 900:  # -1 min to +15 min window
                                continue
                            
                            # Get transfer amount from data field
                            data = log.get("data", "0x0")
                            tx_value = int(data, 16)
                            tx_amount = tx_value / 1_000_000  # USDC has 6 decimals
                            
                            # Check amount with tolerance for fees (~$1-2)
                            amount_diff = abs(tx_amount - amount_usd)
                            
                            if amount_diff < 2:  # Within $2 tolerance
                                logger.info(
                                    f"[Withdrawal Tracker] ✅ Found matching tx: {tx_hash[:20]}... "
                                    f"amount=${tx_amount:.2f}, time_diff={time_diff:.0f}s"
                                )
                                return tx_hash
                            else:
                                logger.debug(
                                    f"[Withdrawal Tracker] Amount mismatch in {tx_hash[:15]}...: "
                                    f"expected ${amount_usd:.2f}, got ${tx_amount:.2f}"
                                )
                
                logger.debug("[Withdrawal Tracker] No matching transaction found yet")
                return None
        
        except Exception as e:
            logger.error(f"[Withdrawal Tracker] Error finding tx: {e}")
            return None
    
    async def _notify_confirmed(self, withdrawal: WithdrawalInfo) -> None:
        """Send notification for confirmed withdrawal."""
        message = (
            f"✅ <b>Withdrawal Confirmed!</b>\n\n"
            f"Amount: <code>${withdrawal.amount_usd:.2f}</code>\n"
            f"Network: Arbitrum\n"
            f"Confirmations: {withdrawal.confirmations}\n"
        )
        
        if withdrawal.tx_hash:
            message += f"\n<a href='https://arbiscan.io/tx/{withdrawal.tx_hash}'>View on Arbiscan</a>"
        
        await self._send_notification(withdrawal, message)
    
    async def _notify_failed(self, withdrawal: WithdrawalInfo) -> None:
        """Send notification for failed withdrawal."""
        message = (
            f"❌ <b>Withdrawal Failed</b>\n\n"
            f"Amount: <code>${withdrawal.amount_usd:.2f}</code>\n"
            f"The transaction failed on Arbitrum.\n"
        )
        
        if withdrawal.tx_hash:
            message += f"\n<a href='https://arbiscan.io/tx/{withdrawal.tx_hash}'>View on Arbiscan</a>"
        
        await self._send_notification(withdrawal, message)
    
    async def _notify_timeout(self, withdrawal: WithdrawalInfo) -> None:
        """Send notification for timeout (transaction not found)."""
        message = (
            f"⏰ <b>Withdrawal Status Unknown</b>\n\n"
            f"Amount: <code>${withdrawal.amount_usd:.2f}</code>\n"
            f"Could not confirm transaction within 15 minutes.\n"
            f"Please check your wallet manually.\n"
        )
        
        if withdrawal.tx_hash:
            message += f"\n<a href='https://arbiscan.io/tx/{withdrawal.tx_hash}'>View on Arbiscan</a>"
        else:
            message += f"\nWallet: <code>{withdrawal.wallet_address}</code>"
        
        await self._send_notification(withdrawal, message)
    
    async def _send_notification(self, withdrawal: WithdrawalInfo, message: str) -> None:
        """Send notification via callback."""
        if self._notification_callback:
            try:
                await self._notification_callback(withdrawal, message)
                logger.info(
                    f"[Withdrawal Tracker] Sent notification to user {withdrawal.telegram_user_id}"
                )
            except Exception as e:
                logger.error(f"[Withdrawal Tracker] Failed to send notification: {e}")
        else:
            logger.warning("[Withdrawal Tracker] No notification callback set")
    
    def get_pending_count(self) -> int:
        """Get number of pending withdrawals being tracked."""
        return len(self._pending_withdrawals)
    
    async def stop_all(self) -> None:
        """Stop all tracking tasks."""
        for task in self._tracking_tasks.values():
            task.cancel()
        
        # Wait for all tasks to complete
        if self._tracking_tasks:
            await asyncio.gather(*self._tracking_tasks.values(), return_exceptions=True)
        
        self._pending_withdrawals.clear()
        self._tracking_tasks.clear()
        logger.info("[Withdrawal Tracker] All tracking stopped")


# Singleton instance
_tracker: Optional[WithdrawalTracker] = None


def get_withdrawal_tracker() -> WithdrawalTracker:
    """Get or create the withdrawal tracker instance."""
    global _tracker
    
    if _tracker is None:
        _tracker = WithdrawalTracker()
    
    return _tracker


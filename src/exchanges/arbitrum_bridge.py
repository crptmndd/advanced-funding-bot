"""
Arbitrum Bridge utilities for HyperLiquid deposits.

This module handles:
- Checking USDC balance on Arbitrum
- Depositing USDC to HyperLiquid via the bridge contract
"""

import logging
from typing import Optional, Tuple
from decimal import Decimal

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

# Logger
logger = logging.getLogger(__name__)

# Arbitrum One configuration
ARBITRUM_RPC_URL = "https://arb1.arbitrum.io/rpc"
ARBITRUM_CHAIN_ID = 42161

# USDC contract on Arbitrum One (Circle's native USDC)
USDC_CONTRACT_ADDRESS = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
USDC_DECIMALS = 6

# HyperLiquid Bridge2 contract on Arbitrum One
HYPERLIQUID_BRIDGE_ADDRESS = "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7"

# Minimum deposit amount (5 USDC)
MIN_DEPOSIT_USDC = 5.0

# ERC20 ABI for balanceOf and transfer
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]


def get_web3() -> Web3:
    """Get Web3 instance connected to Arbitrum."""
    w3 = Web3(Web3.HTTPProvider(ARBITRUM_RPC_URL))
    if not w3.is_connected():
        raise ConnectionError("Failed to connect to Arbitrum RPC")
    return w3


def get_usdc_balance(wallet_address: str) -> Tuple[float, int]:
    """
    Get USDC balance for a wallet on Arbitrum.
    
    Args:
        wallet_address: EVM wallet address
        
    Returns:
        Tuple of (balance_float, balance_raw)
        balance_float is human-readable (e.g., 100.50)
        balance_raw is in smallest units (e.g., 100500000)
    """
    logger.info(f"[Arbitrum] Checking USDC balance for {wallet_address[:10]}...")
    
    try:
        w3 = get_web3()
        
        # Create contract instance
        usdc_contract = w3.eth.contract(
            address=Web3.to_checksum_address(USDC_CONTRACT_ADDRESS),
            abi=ERC20_ABI
        )
        
        # Get balance
        balance_raw = usdc_contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call()
        
        # Convert to human-readable
        balance_float = balance_raw / (10 ** USDC_DECIMALS)
        
        logger.info(f"[Arbitrum] USDC balance: {balance_float:.2f} USDC ({balance_raw} raw)")
        
        return balance_float, balance_raw
        
    except Exception as e:
        logger.error(f"[Arbitrum] Failed to get USDC balance: {e}")
        raise


def get_eth_balance(wallet_address: str) -> float:
    """
    Get ETH balance for a wallet on Arbitrum (needed for gas).
    
    Args:
        wallet_address: EVM wallet address
        
    Returns:
        ETH balance in ether
    """
    logger.info(f"[Arbitrum] Checking ETH balance for {wallet_address[:10]}...")
    
    try:
        w3 = get_web3()
        
        balance_wei = w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
        balance_eth = w3.from_wei(balance_wei, 'ether')
        
        logger.info(f"[Arbitrum] ETH balance: {balance_eth:.6f} ETH")
        
        return float(balance_eth)
        
    except Exception as e:
        logger.error(f"[Arbitrum] Failed to get ETH balance: {e}")
        raise


def deposit_usdc_to_hyperliquid(
    private_key: str,
    amount_usdc: Optional[float] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Deposit USDC from Arbitrum wallet to HyperLiquid.
    
    The deposit is done by sending USDC to the HyperLiquid bridge contract.
    Funds are credited to the same address on HyperLiquid within ~1 minute.
    
    Args:
        private_key: Private key of the wallet
        amount_usdc: Amount to deposit in USDC. If None, deposits entire balance.
        
    Returns:
        Tuple of (success, tx_hash, error_message)
    """
    logger.info(f"[Arbitrum] Starting USDC deposit to HyperLiquid...")
    
    try:
        # Ensure private key has 0x prefix
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        
        # Get account from private key
        account = Account.from_key(private_key)
        wallet_address = account.address
        
        logger.info(f"[Arbitrum] Wallet: {wallet_address[:10]}...{wallet_address[-4:]}")
        
        # Get current USDC balance
        balance_float, balance_raw = get_usdc_balance(wallet_address)
        
        if balance_float < MIN_DEPOSIT_USDC:
            error = f"Insufficient USDC balance. Have {balance_float:.2f}, need at least {MIN_DEPOSIT_USDC}"
            logger.error(f"[Arbitrum] {error}")
            return False, None, error
        
        # Determine amount to deposit
        if amount_usdc is None:
            # Deposit entire balance
            amount_raw = balance_raw
            amount_usdc = balance_float
        else:
            if amount_usdc < MIN_DEPOSIT_USDC:
                error = f"Minimum deposit is {MIN_DEPOSIT_USDC} USDC"
                logger.error(f"[Arbitrum] {error}")
                return False, None, error
            
            if amount_usdc > balance_float:
                error = f"Insufficient balance. Have {balance_float:.2f}, want to deposit {amount_usdc}"
                logger.error(f"[Arbitrum] {error}")
                return False, None, error
            
            amount_raw = int(amount_usdc * (10 ** USDC_DECIMALS))
        
        logger.info(f"[Arbitrum] Depositing {amount_usdc:.2f} USDC ({amount_raw} raw)")
        
        # Check ETH balance for gas
        eth_balance = get_eth_balance(wallet_address)
        if eth_balance < 0.00001:
            error = f"Insufficient ETH for gas. Have {eth_balance:.6f} ETH, need at least 0.00001"
            logger.error(f"[Arbitrum] {error}")
            return False, None, error
        
        # Connect to Arbitrum
        w3 = get_web3()
        
        # Create USDC contract instance
        usdc_contract = w3.eth.contract(
            address=Web3.to_checksum_address(USDC_CONTRACT_ADDRESS),
            abi=ERC20_ABI
        )
        
        # Build transaction
        bridge_address = Web3.to_checksum_address(HYPERLIQUID_BRIDGE_ADDRESS)
        
        # Get nonce
        nonce = w3.eth.get_transaction_count(wallet_address)
        
        # Estimate gas
        try:
            gas_estimate = usdc_contract.functions.transfer(
                bridge_address,
                amount_raw
            ).estimate_gas({'from': wallet_address})
            gas_limit = int(gas_estimate * 1.2)  # Add 20% buffer
        except ContractLogicError as e:
            logger.error(f"[Arbitrum] Gas estimation failed: {e}")
            gas_limit = 100000  # Fallback
        
        # Get gas fees for EIP-1559 transaction
        # On Arbitrum, we need to use maxFeePerGas and maxPriorityFeePerGas
        latest_block = w3.eth.get_block('latest')
        base_fee = latest_block.get('baseFeePerGas') or 0
        
        if base_fee == 0 or base_fee is None:
            # Fallback to legacy gas price if base fee not available
            gas_price = w3.eth.gas_price
            max_priority_fee = w3.to_wei(0.1, 'gwei')  # 0.1 Gwei priority fee
            # Add 50% buffer to ensure transaction goes through
            max_fee = int(gas_price * 1.5) + max_priority_fee
        else:
            # EIP-1559 transaction
            max_priority_fee = w3.to_wei(0.1, 'gwei')  # 0.1 Gwei priority fee on Arbitrum
            # Add 50% buffer to base fee to ensure transaction goes through even if base fee increases
            max_fee = int(base_fee * 1.5) + max_priority_fee
        
        logger.info(f"[Arbitrum] Building transaction...")
        logger.info(f"[Arbitrum] Nonce: {nonce}")
        logger.info(f"[Arbitrum] Gas limit: {gas_limit}")
        logger.info(f"[Arbitrum] Base fee: {w3.from_wei(base_fee, 'gwei'):.4f} Gwei")
        logger.info(f"[Arbitrum] Max priority fee: {w3.from_wei(max_priority_fee, 'gwei'):.4f} Gwei")
        logger.info(f"[Arbitrum] Max fee per gas: {w3.from_wei(max_fee, 'gwei'):.4f} Gwei")
        
        # Build the transaction (EIP-1559 type 2)
        tx = usdc_contract.functions.transfer(
            bridge_address,
            amount_raw
        ).build_transaction({
            'from': wallet_address,
            'nonce': nonce,
            'gas': gas_limit,
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': max_priority_fee,
            'chainId': ARBITRUM_CHAIN_ID,
            'type': 2,  # EIP-1559 transaction
        })
        
        # Sign transaction
        logger.info(f"[Arbitrum] Signing transaction...")
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        
        # Send transaction
        logger.info(f"[Arbitrum] Sending transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        tx_hash_hex = tx_hash.hex()
        
        logger.info(f"[Arbitrum] Transaction sent! Hash: {tx_hash_hex}")
        logger.info(f"[Arbitrum] View on Arbiscan: https://arbiscan.io/tx/{tx_hash_hex}")
        
        # Wait for confirmation (optional, with timeout)
        logger.info(f"[Arbitrum] Waiting for confirmation...")
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            
            if receipt['status'] == 1:
                logger.info(f"[Arbitrum] ✅ Transaction confirmed! Block: {receipt['blockNumber']}")
                logger.info(f"[Arbitrum] Gas used: {receipt['gasUsed']}")
                return True, tx_hash_hex, None
            else:
                error = "Transaction failed (reverted)"
                logger.error(f"[Arbitrum] {error}")
                return False, tx_hash_hex, error
                
        except Exception as e:
            # Transaction sent but confirmation timed out - it may still succeed
            logger.warning(f"[Arbitrum] Confirmation timeout, but tx was sent: {e}")
            return True, tx_hash_hex, f"Transaction sent, confirmation pending: {tx_hash_hex}"
        
    except Exception as e:
        logger.exception(f"[Arbitrum] Failed to deposit USDC")
        return False, None, str(e)


def format_balance_message(wallet_address: str) -> Tuple[str, float, float]:
    """
    Format a message showing wallet balances on Arbitrum.
    
    Args:
        wallet_address: EVM wallet address
        
    Returns:
        Tuple of (formatted_message, usdc_balance, eth_balance)
    """
    try:
        usdc_balance, _ = get_usdc_balance(wallet_address)
        eth_balance = get_eth_balance(wallet_address)
        
        lines = [
            f"💰 <b>Arbitrum Balances</b>",
            f"",
            f"USDC: <code>{usdc_balance:.2f}</code>",
            f"ETH (for gas): <code>{eth_balance:.6f}</code>",
        ]
        
        if usdc_balance < MIN_DEPOSIT_USDC:
            lines.append("")
            lines.append(f"⚠️ Minimum deposit: {MIN_DEPOSIT_USDC} USDC")
        
        if eth_balance < 0.00001:
            lines.append("")
            lines.append(f"⚠️ Need ETH for gas fees")
        
        return "\n".join(lines), usdc_balance, eth_balance
        
    except Exception as e:
        return f"❌ Failed to check balance: {e}", 0.0, 0.0


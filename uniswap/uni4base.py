import os
import json
import time
import logging
import functools
from typing import List, Any, Optional, Callable, Union, Tuple, Dict

from web3 import Web3
from web3.types import (
    TxParams,
    Wei,
    Address,
    ChecksumAddress,
    ENS,
    Nonce,
    HexBytes,
)
from eth_utils import is_same_address
from eth_typing import AnyAddress

ZERO_HOOK = "0x0000000000000000000000000000000000000000"
ETH_ADDRESS = "0x0000000000000000000000000000000000000000"
WRAPPED_ETH_ADDRESS = "0xc207eb4dF2E25c180902257aF349d841022561E8"


class pool_key:
    currency0 : str
    currency1 : str
    fee : int
    tick_spacing : int
    hooks : str


class InvalidToken(Exception):
    def __init__(self, address: Any) -> None:
        Exception.__init__(self, f"Invalid token address: {address}")


class InsufficientBalance(Exception):
    def __init__(self, had: int, needed: int) -> None:
        Exception.__init__(self, f"Insufficient balance. Had {had}, needed {needed}")


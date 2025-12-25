from web3 import Web3
import eth_abi.abi
from web3.contract import Contract
from web3.contract.contract import ContractFunction
from eth_typing import AnyAddress
from eth_abi.codec import ABICodec
from eth_abi import encode
from eth_abi.packed import encode_packed
import os
import fnmatch
import configparser
from uni4base import *
import logging
from decimal import Decimal
##from colorama import Fore
##from colorama import Style
from typing import List, Any, Optional, Callable, Union, Tuple, Dict
from web3.types import (
    TxParams,
    Wei,
    Address,
    ChecksumAddress,
    ENS,
    Nonce,
    HexBytes,
)
import json
import ctypes



AddressLike = Union[Address, ChecksumAddress, ENS]
_netid_to_name = {1000: "mainnet", 1001: "nile"}
with open(os.path.abspath(f"assets\\erc20.abi")) as f:
        erc20_ABI : str = json.load(f)

eth_by_dex = {
    "UNISWAPV4" : ETH_ADDRESS,
}
transfer_by_dex = {
    "UNISWAPV4" : WRAPPED_ETH_ADDRESS,
}
weth_by_dex = {
            "UNISWAPV4" : WRAPPED_ETH_ADDRESS,
}

def _addr_to_str(a: AddressLike) -> str:
    if isinstance(a, bytes):
        # Address or ChecksumAddress
        addr : str = Web3.to_checksum_address("0x" + bytes(a).hex())
        return addr
    elif isinstance(a, str):
        if a.endswith(".ens"):
            # Address is ENS
            raise Exception("ENS not supported for this operation")
        elif a.startswith("0x"):
            addr = Web3.to_checksum_address(a)
            return addr
        else:
            raise InvalidToken(a)

def _str_to_addr(s: str) -> AddressLike:
    if s.startswith("0x"):
        return Address(bytes.fromhex(s[2:]))
    elif s.endswith(".ens"):
        return ENS(s)
    else:
        raise Exception("Could't convert string {s} to AddressLike")

def is_version3(dex: str) -> bool:
    if "V3" in dex:
        return True
    else:
        return False

class Uniswap4():
    def __init__(self,
        address: Union[str, AddressLike],
        private_key: str,
        provider: str=None,
        web3: Web3=None,
        version: int=4,
        max_slippage: float=0.1,
        max_gas: float=250001.0,
        max_gprice: float=18.0,
        dex_name: str="",
        london_fork: int=1,
        max_priorityfee: float=2.0,) -> None:

        self.address : AddressLike = _str_to_addr(address) if isinstance(address, str) else address
        self.private_key = private_key
        self.version = version

        self.max_slippage = max_slippage

        if web3:
            self.w3 = web3
        else:
            self.provider = provider or os.environ["PROVIDER"]
            self.w3 = Web3(Web3.HTTPProvider(self.provider, request_kwargs={"timeout": 60}))

        self.last_nonce : Nonce = self.w3.eth.get_transaction_count(self.address)

        # This code automatically approves you for trading on the exchange.
        # max_approval is to allow the contract to exchange on your behalf.
        # max_approval_check checks that current approval is above a reasonable
        # number
        # The program cannot check for max_approval each time because it
        # decreases
        # with each trade.
        self.max_approval_hex = f"0x{64 * 'f'}"
        self.max_approval_int = int(self.max_approval_hex, 16)
        self.max_approval_check_hex = f"0x{15 * '0'}{49 * 'f'}"
        self.max_approval_check_int = int(self.max_approval_check_hex, 16)
        self.gas_limit = max_gas
        self.gas_price = max_gprice
        self.london_style = london_fork
        self.london_priorityfee = max_priorityfee
        self.dex_name = dex_name

        chain_id = self.w3.net.version
        config = configparser.ConfigParser()
        config.read("configs\\evmuniV4_quoter.ini")
        quoter_address = config.get("settings",chain_id)
        config.read("configs\\evmuniV4_router.ini")
        router_address = config.get("settings",chain_id)
        config.read("configs\\evmuniV4_stateview.ini")
        stateview_address = config.get("settings",chain_id)
        config.read("configs\\evmuniV4_permit2.ini")
        permit2_address = config.get("settings",chain_id)

        self.quoter_address = _str_to_addr(quoter_address)
        self.router_address = _str_to_addr(router_address)
        self.stateview_address = _str_to_addr(stateview_address)
        self.permit2_address = _str_to_addr(permit2_address)

        self.quoter = _load_contract(self.w3, abi_name = "uniswap-v4/quoter", address = self.quoter_address)
        self.router = _load_contract(self.w3, abi_name="uniswap-v4/router", address=self.router_address)
        self.stateview = _load_contract(self.w3, abi_name="uniswap-v4/stateview", address=self.stateview_address)
        self.permit2 = _load_contract(self.w3, abi_name="uniswap-v4/permit2", address=self.permit2_address)
        weth_by_dex[dex_name] = WRAPPED_ETH_ADDRESS
        return

    def load_contract_with_abi(self, abi_name: str, address: AddressLike) -> Contract:
        return self.w3.eth.contract(address=address, abi=_load_abi(abi_name))

    def erc20_contract(self, token_addr: AddressLike) -> Contract:
        return self.load_contract_with_abi(abi_name="erc20", address=token_addr)

    def approve(self, token: AddressLike, max_approval: Optional[int]=None) -> Any:    #<-------------------- FIX ME
        """Give an PERMIT2 approval of a token."""
        if(token != ETH_ADDRESS):
            max_approval = self.max_approval_int if not max_approval else max_approval
            function = self.erc20_contract(token).functions.approve(_addr_to_str(self.permit2_address), max_approval)
            print(f"Approving {_addr_to_str(token)} for PERMIT2...")
            tx = self._build_and_send_tx(function)
            time.sleep(7)
        #Give an exchange/router max approval of a token.
        max_approval :int = 2 ** 100 - 1
        expiration :int = int(10 ** 12)
        print(f"Setting permit for {_addr_to_str(token)} at router contract...")
        function = self.permit2.functions.approve(_str_to_addr(token), self.router_address, max_approval, expiration)
        tx = self._build_and_send_tx(function)

        return tx

    def approval(self,token: AddressLike):
        #[0] current allowance, [1] allowance expiration [2] current nonce
        result = int(self.permit2.functions.allowance(self.address, token, self.router.address).call()[0])
        return result

    def _get_tx_params(self, value: int=0 , gas: int=250001) -> dict:
        """Get generic transaction parameters."""
        if self.london_style == 0:
            return {
                "from": _addr_to_str(self.address),
                "value": value,
                "gas": int(self.gas_limit),
                "gasPrice": Web3.to_wei(self.gas_price, 'gwei'),
                "nonce": max(self.last_nonce, 0),
            }
        else:
            return {
                "from": _addr_to_str(self.address),
                "gas": int(self.gas_limit),
                "maxPriorityFeePerGas": Web3.to_wei(self.london_priorityfee, 'gwei'),
                "maxFeePerGas": Web3.to_wei(self.gas_price, 'gwei'),
                "type": 2,
                "chainId": self.w3.eth.chain_id,
                "value": value,
                "nonce": max(self.last_nonce, 0),
            }


    def get_token_token_spot_price(self, token0: str, token1: str, fee: int, tick_spacing: int, hooks: str) -> int:
        """Current spot price for token to token trades."""
        if token0 > token1:
            (token1, token0) = (token0, token1)
        pool_key = eth_abi.abi.encode(types=["address", "address", "uint24", "int24", "address"],
                    args=[token0,
                        token1,
                        fee,
                        tick_spacing,
                        hooks,],)
        pool_id = Web3.keccak(pool_key)
        if self.version == 4:
            price : int = self.stateview.functions.getSlot0(pool_id.hex()).call()[0]
        else:
            raise ValueError("Function not supported for this version of Sunswap")
        return price

    def get_quote_exact_input_single(self, token0: AddressLike, token1: AddressLike, qty: int, fee: int=500, tick_spacing: int=10, hooks: AddressLike=ZERO_HOOK, hook_data:bytes=bytes()) -> int:
        """Quote for token to token single hop trades with an exact input."""
        if self.version == 4:
            if(token0 < token1):
                zero_for_one = True
            else:
                zero_for_one = False
                (token1, token0) = (token0, token1)
            pool_key = (token0,
                        token1,
                        fee,
                        tick_spacing,
                        hooks)
            #[0] The output quote [1] estimated gas units used for the swap
            price : int = self.quoter.functions.quoteExactInputSingle((pool_key, zero_for_one,qty, hook_data)).call()[0]
        else:
            raise ValueError("Function not supported for this version of Sunswap")
        return price

    def get_quote_exact_output_single(self, token0: AddressLike, token1: AddressLike, qty: int, fee: int=500, tick_spacing: int=10, hooks: AddressLike=ZERO_HOOK, hook_data:bytes=bytes()) -> int:
        """Quote for token to token single hop trades with an exact output."""
        if self.version == 4:
            if(token0 < token1):
                zero_for_one = True
            else:
                zero_for_one = False
                (token1, token0) = (token0, token1)

            pool_key = (token0,
                        token1,
                        fee,
                        tick_spacing,
                        hooks,)
            #[0] The input quote [1] estimated gas units used for the swap
            price : int = self.quoter.functions.quoteExactOutputSingle((pool_key, zero_for_one,qty, hook_data)).call()[0]
        else:
            raise ValueError("Function not supported for this version of Sunswap")
        return price

    def _token_to_token_swap_input(self,
        input_token: str,
        qty: int,
        qtycap: int,
        output_token: str,
        recipient: Optional[AddressLike],
        fee: int,
        tick_spacing: int,
        hooks: str,) -> HexBytes:
        if self.version == 4:
            if recipient is None:
                recipient = self.address

            min_tokens_bought = int((1 - self.max_slippage) * qtycap)
            
            ether_amount = 0
            if(input_token == ETH_ADDRESS):
                ether_amount = qty

            #V4_SWAP // Encode swap actions
            commands = encode_packed(["uint8"], args=[0x10],)

            #SWAP_EXACT_IN_SINGLE, SETTLE_ALL, TAKE_ALL
            actions = encode_packed(["uint8","uint8","uint8"], [0x06, 0x0C, 0x0F],)

            #SETTING PARAMS
            pool_key = (input_token,
                        output_token,
                        fee,
                        tick_spacing,
                        hooks)
            if input_token < output_token:
                zero_for_one = True
                (token0, token1) = (input_token, output_token)
            else:
                zero_for_one = False
                (token0, token1) = (output_token,input_token)
            exact_input_single_params = encode(['((address,address,uint24,int24,address),bool,int128,uint128,bytes)'],
                                              [((token0, token1, fee, tick_spacing, hooks), zero_for_one, qty, min_tokens_bought, bytes(0))],)
            settle_all_params = encode(['address','uint128'], [input_token, qty],)
            take_all_params = encode(['address','uint128'], [output_token, min_tokens_bought],)

            #ENCODING DATA
            params = [exact_input_single_params, settle_all_params, take_all_params]
            inputs = []
            inputs.append(encode(['bytes','bytes[]'], [actions, params],))

            return self._build_and_send_tx(self.router.functions.execute(commands, inputs, self._deadline()), self._get_tx_params(value=ether_amount))
        else:
            raise ValueError


    def _token_to_token_swap_output(self,
        input_token: AddressLike,
        qty: int,
        qtycap: int,
        output_token: AddressLike,
        recipient: Optional[AddressLike],
        fee: int,
        tick_spacing,
        hooks: AddressLike,) -> HexBytes:
        if self.version == 4:
            if recipient is None:
                recipient = self.address

            amount_in_max = int((1 + self.max_slippage) * qtycap)

            ether_amount = 0
            if(input_token == ETH_ADDRESS):
                ether_amount = qty

            #V4_SWAP // Encode swap actions
            commands = encode_packed(["uint8"],
                args=[0x10],)

            #SWAP_EXACT_OUT_SINGLE, SETTLE_ALL, TAKE_ALL
            actions = encode_packed(["uint8","uint8","uint8"],
                args=[0x09, 0x0C, 0x0F],)
            #SETTING PARAMS
            pool_key = (input_token,
                        output_token,
                        fee,
                        tick_spacing,
                        hooks,)
            if input_token < output_token:
                zero_for_one = True
                (token0, token1) = (input_token, output_token)
            else:
                zero_for_one = False
                (token0, token1) = (output_token,input_token)
            exact_output_single_params = encode(['((address,address,uint24,int24,address),bool,int128,uint128,bytes)'],
                                                [((token0, token1,fee,tick_spacing,hooks,), zero_for_one, qty, amount_in_max, bytes(0))],)
            settle_all_params = encode(["address","uint128"], [input_token, amount_in_max],)
            take_all_params = encode(["address","uint128"], [output_token, qty],)

            #ENCODING DATA
            params = (exact_output_single_params, settle_all_params, take_all_params)
            inputs = []
            inputs.append(encode(["bytes","bytes[]"], [actions, params],))

            return self._build_and_send_tx(self.router.functions.execute(commands, inputs, self._deadline()), self._get_tx_params(value=ether_amount))
        else:
            raise ValueError



    def drop_txn(self,
        address_to: AddressLike,
        gwei: float,
        gasv: float,
        priorityfee: int=10) -> HexBytes:

        signed_txn = self.w3.eth.account.sign_transaction(dict(chainId=int(self.w3.net.version),
                                                              nonce=self.last_nonce,
                                                              gasPrice = Web3.to_wei(self.gas_price, 'gwei'),
                                                              gas = int(self.gas_limit),
                                                              to = Web3.to_checksum_address(address_to),
                                                              value = Web3.to_wei(0,'wei')), self.private_key)
        signed_txn_london = self.w3.eth.account.sign_transaction(dict(chainId=int(self.w3.net.version),
                                                              type=2,
                                                              nonce=self.last_nonce,
                                                              maxFeePerGas = Web3.to_wei(int(gwei), 'gwei'),
                                                              maxPriorityFeePerGas = Web3.to_wei(priorityfee, 'gwei'),
                                                              gas = int(21000),
                                                              to = Web3.to_checksum_address(address_to),
                                                              value = Web3.to_wei(0,'wei')), self.private_key)
        if self.london_style == 1:
            return self.w3.eth.send_raw_transaction(signed_txn_london.rawTransaction)  
        else:
            return self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)  

    def make_swap_input(self,
        input_token: AddressLike,
        output_token: AddressLike,
        qty: int,
        qtycap: int,
        swap_pool_key: pool_key,
        recipient: AddressLike=None,
        fee: int=3000) -> HexBytes:
        
        return self._token_to_token_swap_input(input_token, qty, qtycap, output_token, recipient, swap_pool_key.fee, swap_pool_key.tick_spacing, swap_pool_key.hooks)

    def make_swap_output(self,
        input_token: AddressLike,
        output_token: AddressLike,
        qty: int,
        qtycap: int,
        swap_pool_key: pool_key,
        recipient: AddressLike=None,
        fee: int=3000) -> HexBytes:
        
        return self._token_to_token_swap_output(swap_pool_key.currency0, qty, qtycap, swap_pool_key.currency1, recipient, swap_pool_key.fee, swap_pool_key.tick_spacing, swap_pool_key.hooks)
    
    def get_weth_address(self) -> AddressLike:
        address : str = weth_by_dex[self.dex_name]()
        return address

    def get_token_balance(self, erc20: AddressLike) -> Decimal:

        contract = _load_contract(self.w3, abi_name = "erc20", address = erc20)
        decimals = contract.functions.decimals().call()
        try:
            balance = contract.functions.balanceOf(self.address).call()
        except:
            balance = 0
        balance = Decimal(balance) / (10 ** decimals)
        return balance

    def get_balance(self) -> Decimal:
        """Get the balance of ETH for your address."""
        try:
            balance = self.w3.eth.get_balance(self.address)
        except:
            balance = 0
        return balance

    def _deadline(self) -> int:
        """Get a predefined deadline. 10min by default."""
        return int(time.time()) + 10 * 60

    def _build_and_send_tx(self, function: ContractFunction, tx_params: Optional[dict]=None) -> HexBytes:
        """Build and send a transaction."""
        if not tx_params:
            tx_params = self._get_tx_params()
        transaction = function.build_transaction(tx_params)
        signed_txn = self.w3.eth.account.sign_transaction(transaction, private_key=self.private_key)
        # TODO: This needs to get more complicated if we want to support
        # replacing a transaction
        # FIXME: This does not play nice if transactions are sent from other
        # places using the same wallet.
        try:
            return self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        finally:
            #logger.debug(f"nonce: {tx_params['nonce']}")
            self.last_nonce = Nonce(tx_params["nonce"] + 1)


def _load_contract(w3: Web3, abi_name: str, address: AddressLike) -> Contract:
    address = Web3.to_checksum_address(address)
    return w3.eth.contract(address=address, abi=_load_abi(abi_name))

def _load_abi(name: str) -> str:
    path = f"{os.path.dirname(os.path.abspath(__file__))}/assets/"
    with open(os.path.abspath(path + f"{name}.abi")) as f:
        abi = json.load(f)
    return abi


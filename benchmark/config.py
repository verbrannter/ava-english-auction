from pathlib import Path
from web3 import Web3

CHAINS = {
    "fuji": {
        "chain_id": 43113,
        "rpc_env": "FUJI_RPC_URL",
        "native": "AVAX",
        "explorer": "https://testnet.snowtrace.io/address",
        "bidder_funding": Web3.to_wei(0.3, "ether"),
        "is_poa": True,
        "auction_duration": 900,
    },
    "sepolia": {
        "chain_id": 11155111,
        "rpc_env": "SEPOLIA_RPC_URL",
        "native": "ETH",
        "explorer": "https://sepolia.etherscan.io/address",
        "bidder_funding": Web3.to_wei(0.05, "ether"),
        "is_poa": False,
        "auction_duration": 3600,
    },
    "monad": {
        "chain_id": 10143,
        "rpc_env": "MONAD_RPC_URL",
        "native": "MON",
        "explorer": "https://testnet.monadvision.com/address",
        "bidder_funding": Web3.to_wei(3, "ether"),
        "is_poa": False,
        "auction_duration": 1800,
    },
    "cronos": {
        "chain_id": 338,
        "rpc_env": "CRONOS_RPC_URL",
        "native": "TCRO",
        "explorer": "https://explorer.cronos.org/testnet/address",
        "bidder_funding": Web3.to_wei(15, "ether"),
        "is_poa": True,
        "auction_duration": 1200,
    }
}

NUM_BIDDERS = 3

AUCTION_PARAMS = {
    "extension_window": 1,
    "extension_duration": 1,
    "initial_price": Web3.to_wei(0.001, "ether"),
    "min_bid_increment": Web3.to_wei(0.0001, "ether"),
}

GAS_LIMIT_BID = 200_000
GAS_LIMIT_TRANSFER = 21_000

RESULTS_DIR = Path("results")
ARTIFACT_NFT = Path("out/MockNFT.sol/MockNFT.json")
ARTIFACT_AUCTION = Path("out/EnglishAuction.sol/EnglishAuction.json")

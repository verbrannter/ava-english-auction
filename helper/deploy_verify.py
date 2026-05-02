import json
import os
import subprocess
import sys
from pathlib import Path

# Configs
CHAIN_ID = "43113"
VERIFIER_URL = "https://api.routescan.io/v2/network/testnet/evm/43113/etherscan"
COMPILER_VERSION = "v0.8.26"
OPTIMIZER_RUNS = "200"
# Parmas
AUCTION_PARAMS = {
    "token_id":          0,
    "base_duration":     3600, # 1 hour
    "absolute_duration": 86400, # 24 hours
    "extension_window":  300, # 5 mins
    "extension_duration": 300, # 5 mins
    "initial_price":     10_000_000_000_000_000, # 0.01 AVAX in wei
    "min_bid_increment": 1_000_000_000_000_000, # 0.001 AVAX in wei
}


def load_env(path=".env"):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            key = key.strip().removeprefix("export ").strip()
            os.environ[key] = value

def run(cmd, capture=False, check=True):
    print(f"${' '.join(cmd)}", flush=True)
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            sys.exit(f"Command failed (exit {result.returncode})")
        return result.stdout
    else:
        result = subprocess.run(cmd)
        if check and result.returncode != 0:
            sys.exit(f"Command failed (exit {result.returncode})")
        return None

def deploy():
    print("Deploying MockNFT and EnglishAuction")
    run([
        "forge", "script", "script/Deploy.s.sol:DeployScript",
        "--rpc-url", os.environ["FUJI_RPC_URL"],
        "--broadcast",
    ])


def get_deployed_addresses():
    broadcast_path = Path(f"broadcast/Deploy.s.sol/{CHAIN_ID}/run-latest.json")

    with open(broadcast_path) as f:
        data = json.load(f)

    nft_addr = None
    auction_addr = None

    for tx in data.get("transactions", []):
        if tx.get("transactionType") != "CREATE":
            continue
        name = tx.get("contractName", "")
        addr = tx.get("contractAddress")
        if name == "MockNFT":
            nft_addr = addr
        elif name == "EnglishAuction":
            auction_addr = addr

    if not nft_addr or not auction_addr:
        sys.exit("Couldn't find both MockNFT and EnglishAuction in broadcast file.")

    return nft_addr, auction_addr

def encode_constructor_args(nft_addr):
    """Use `cast abi-encode` to encode the auction constructor args."""
    p = AUCTION_PARAMS
    output = run([
        "cast", "abi-encode",
        "constructor(address,uint256,uint256,uint256,uint256,uint256,uint256,uint256)",
        nft_addr,
        str(p["token_id"]),
        str(p["base_duration"]),
        str(p["absolute_duration"]),
        str(p["extension_window"]),
        str(p["extension_duration"]),
        str(p["initial_price"]),
        str(p["min_bid_increment"]),
    ], capture=True)
    return output.strip()

def verify(addr, contract_path, constructor_args=None):
    cmd = [
        "forge", "verify-contract",
        addr,
        contract_path,
        "--verifier-url", VERIFIER_URL,
        "--etherscan-api-key", "verifyContract",
        "--num-of-optimizations", OPTIMIZER_RUNS,
        "--compiler-version", COMPILER_VERSION,
        "--watch",
    ]
    if constructor_args:
        cmd.extend(["--constructor-args", constructor_args])
    run(cmd, check=False)


def main():
    load_env()
    deploy()

    nft_addr, auction_addr = get_deployed_addresses()
    print(f"MockNFT deployed: {nft_addr}")
    print(f"EnglishAuction deployed: {auction_addr}")

    print("Verifying MockNFT on Snowtrace")
    verify(nft_addr, "src/MockNFT.sol:MockNFT")

    print("Verifying EnglishAuction on Snowtrace")
    args = encode_constructor_args(nft_addr)
    verify(auction_addr, "src/EnglishAuction.sol:EnglishAuction", constructor_args=args)

    print("Done!")
    print(f"MockNFT: https://testnet.snowtrace.io/address/{nft_addr}")
    print(f"EnglishAuction: https://testnet.snowtrace.io/address/{auction_addr}")


if __name__ == "__main__":
    main()

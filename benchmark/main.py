import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account

from config import (
    CHAINS, NUM_BIDDERS, AUCTION_PARAMS,
    GAS_LIMIT_BID, GAS_LIMIT_TRANSFER,
    RESULTS_DIR, ARTIFACT_NFT, ARTIFACT_AUCTION,)

def load_env(path=".env"):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ[k.strip().removeprefix("export ").strip()] = (v.strip().strip('"').strip("'"))

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--chain", choices=list(CHAINS.keys()), default="fuji")
    p.add_argument("--bids", type=int, default=100)
    p.add_argument("--rpc-url")
    return p.parse_args()


def load_artifact(path):
    with open(path) as f:
        data = json.load(f)
    return data["abi"], data["bytecode"]["object"]

def now_ms():
    return time.time() * 1000

def wait_for_tx(w3, tx_hash, propagate_attempts=15):
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    target_block = receipt.blockNumber

    for _ in range(propagate_attempts):
        try:
            current = w3.eth.block_number
            if current >= target_block:
                w3.eth.get_transaction_receipt(tx_hash)
                return receipt
        except Exception:
            pass
        time.sleep(0.5)

    return receipt

def send_tx(w3, key, chain_id, fn_call=None, to=None, value=0, gas=None):
    account = Account.from_key(key)
    tx = {
        "from":     account.address,
        "value":    value,
        "chainId":  chain_id,
        "nonce":    w3.eth.get_transaction_count(account.address, "pending"),
        "gasPrice": w3.eth.gas_price,
    }
    if fn_call is not None:
        tx = fn_call.build_transaction(tx)
        if gas is not None:
            tx["gas"] = gas
    else:
        tx["to"] = to
        tx["gas"] = gas if gas is not None else GAS_LIMIT_TRANSFER

    signed = account.sign_transaction(tx)
    sent_at = now_ms()
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    return h, sent_at

def deploy_contract(w3, key, chain_id, abi, bytecode, args=()):
    Factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    h, _ = send_tx(w3, key, chain_id, fn_call=Factory.constructor(*args))
    receipt = wait_for_tx(w3, h)
    return w3.eth.contract(address=receipt.contractAddress, abi=abi)

def deploy_and_start_auction(w3, seller_key, chain):
    seller = Account.from_key(seller_key)
    chain_id = chain["chain_id"]
    explorer = chain["explorer"]

    nft_abi, nft_bytecode = load_artifact(ARTIFACT_NFT)
    auc_abi, auc_bytecode = load_artifact(ARTIFACT_AUCTION)

    nft = deploy_contract(w3, seller_key, chain_id, nft_abi, nft_bytecode, args=("https://algo2018.hiit.fi/tim-roughgarden.jpg",))
    print(f"MockNFT: {nft.address}")
    print(f"{explorer}/{nft.address}")

    h, _ = send_tx(w3, seller_key, chain_id, fn_call=nft.functions.mint(seller.address))
    wait_for_tx(w3, h)

    p = AUCTION_PARAMS
    duration = chain["auction_duration"]
    auction = deploy_contract(
        w3, seller_key, chain_id, auc_abi, auc_bytecode,
        args=(
            nft.address, 0,
            duration, duration,
            p["extension_window"], p["extension_duration"],
            p["initial_price"], p["min_bid_increment"],
        ),
    )
    print(f"EnglishAuction: {auction.address}")
    print(f"{explorer}/{auction.address}")

    h, _ = send_tx(w3, seller_key, chain_id, fn_call=nft.functions.approve(auction.address, 0))
    wait_for_tx(w3, h)

    h, _ = send_tx(w3, seller_key, chain_id, fn_call=auction.functions.start())
    receipt = wait_for_tx(w3, h)

    print("Auction started")

    return auction

def required_msg_value(i, k, initial_price, increment):
    if i == 0:
        return initial_price
    elif i < k:
        return initial_price + (i + 1) * increment
    else:
        return (k + 1) * increment

def run_benchmark(w3, auction, bidder_keys, num_bids, chain_id):
    k = len(bidder_keys)
    print(f"{num_bids} bids, {k} bidders")

    p = AUCTION_PARAMS
    bidders = [Account.from_key(key) for key in bidder_keys]
    rows = []
    benchmark_start = now_ms()

    for i in range(num_bids):
        idx = i % k
        bidder_addr = bidders[idx].address
        value = required_msg_value(i, k, p["initial_price"], p["min_bid_increment"])

        tx_hash, sent_at = send_tx(
            w3, bidder_keys[idx], chain_id,
            fn_call=auction.functions.bid(),
            value=value, gas=GAS_LIMIT_BID,
        )
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        mined_at = now_ms()
        latency = mined_at - sent_at

        gas_price = receipt.get("effectiveGasPrice")
        if gas_price is None:
            gas_price = w3.eth.get_transaction(tx_hash)["gasPrice"]

        rows.append({
            "index": i, "bidder": bidder_addr, "value_wei": value,
            "tx_hash": tx_hash.hex(), "sent_at_ms": sent_at, "mined_at_ms": mined_at,
            "latency_ms": latency, "block": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "effective_gas_price": gas_price,
            "cost_wei": receipt.gasUsed * gas_price,
            "status": "success" if receipt.status == 1 else "reverted",
        })

        if i % 10 == 0:
            print(f"bid {i:>3} latency={latency:.0f}ms gas={receipt.gasUsed} block={receipt.blockNumber}")

    print(f"\nDone in {(now_ms() - benchmark_start) / 1000:.1f}s\n")
    return rows

def settle_auction(w3, auction, seller_key, chain_id):
    end_time = auction.functions.endTime().call()
    while True:
        ts = w3.eth.get_block("latest").timestamp
        if ts >= end_time:
            break
        wait = min(60, max(5, end_time - ts))
        print(f"Waiting for endTime ({end_time - ts}s remaining)...")
        time.sleep(wait)

    h, _ = send_tx(w3, seller_key, chain_id, fn_call=auction.functions.settleAuction(), gas=300_000)
    receipt = wait_for_tx(w3, h)
    print(f"Settled (gas={receipt.gasUsed})\n")

def sweep(w3, bidder_keys, seller_addr, auction, chain_id, native):
    print("Sweeping back to seller...") # gotta recoop funds
    for key in bidder_keys:
        acct = Account.from_key(key)
        pending = auction.functions.pendingReturns(acct.address).call()
        if pending > 0:
            h, _ = send_tx(w3, key, chain_id, fn_call=auction.functions.withdraw(), gas=100_000)
            wait_for_tx(w3, h)

        balance = w3.eth.get_balance(acct.address)
        gas_cost = GAS_LIMIT_TRANSFER * w3.eth.gas_price
        if balance <= gas_cost:
            continue
        amount = balance - gas_cost
        h, _ = send_tx(w3, key, chain_id, to=seller_addr, value=amount)
        wait_for_tx(w3, h)
        print(f"  {acct.address}: {Web3.from_wei(amount, 'ether'):.4f} {native}")
    print()

def write_csv(rows, timestamp, chain_name):
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{timestamp}_{chain_name}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path

def print_summary(rows, native):
    successes = [r for r in rows if r["status"] == "success"]
    reverts   = [r for r in rows if r["status"] == "reverted"]

    print(f"total={len(rows)}  success={len(successes)}  reverted={len(reverts)}")

    if successes:
        latencies = sorted(r["latency_ms"] for r in successes)
        gas_used  = [r["gas_used"] for r in successes]
        costs     = [r["cost_wei"] for r in successes]
        total_cost = sum(costs)
        print(f"\nlatency (ms): min={min(latencies):.0f} "
              f"median={statistics.median(latencies):.0f} "
              f"mean={statistics.mean(latencies):.0f} "
              f"p95={latencies[int(len(latencies) * 0.95)]:.0f} "
              f"p99={latencies[int(len(latencies) * 0.99)]:.0f} "
              f"max={max(latencies):.0f}")
        print(f"gas: median={int(statistics.median(gas_used))} "
              f"mean={int(statistics.mean(gas_used))}")
        print(f"cost per bid ({native}): "
              f"median={Web3.from_wei(int(statistics.median(costs)), 'ether'):.6f} "
              f"mean={Web3.from_wei(int(statistics.mean(costs)), 'ether'):.6f}")
        print(f"total cost ({native}): {Web3.from_wei(total_cost, 'ether'):.4f}\n")

def main():
    args = parse_args()
    load_env()

    chain = CHAINS[args.chain]
    chain_id = chain["chain_id"]
    native = chain["native"]
    explorer = chain["explorer"]

    rpc_url = args.rpc_url or os.environ[chain["rpc_env"]]
    seller_key = os.environ["PRIVATE_KEY"]

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if chain.get("is_poa"):
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    seller = Account.from_key(seller_key)

    print(f"Chain: {args.chain} (id={chain_id})")
    print(f"Seller: {seller.address}")
    print(f"{explorer}/{seller.address}")
    print(f"Balance: {Web3.from_wei(w3.eth.get_balance(seller.address), 'ether'):.4f} {native}\n")

    bidders = [Account.create() for _ in range(NUM_BIDDERS)]
    bidder_keys = [b.key.hex() for b in bidders]
    print(f"Bidders:")
    for i, (b, key) in enumerate(zip(bidders, bidder_keys)):
        print(f"Bidder {i}: {b.address}")
        print(f"key: {key}") # just in case of crashing we can always send back
        print(f"{explorer}/{b.address}")
    print()

    for b in bidders:
        h, _ = send_tx(w3, seller_key, chain_id, to=b.address, value=chain["bidder_funding"])
        wait_for_tx(w3, h)

    auction = deploy_and_start_auction(w3, seller_key, chain)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = run_benchmark(w3, auction, bidder_keys, args.bids, chain_id)
    path = write_csv(rows, timestamp, args.chain)
    print(f"wrote {path}\n")
    print_summary(rows, native)

    settle_auction(w3, auction, seller_key, chain_id)
    sweep(w3, bidder_keys, seller.address, auction, chain_id, native)

    final = w3.eth.get_balance(seller.address)
    print(f"Seller final balance: {Web3.from_wei(final, 'ether'):.4f} {native}")

if __name__ == "__main__":
    main()

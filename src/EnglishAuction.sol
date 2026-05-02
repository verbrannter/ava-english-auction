// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC721} from "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

contract EnglishAuction is ReentrancyGuard {
    // seller and auctioned asset

    // SELLER: the address of the account that created auction
    //  at end of auction, SELLER exchanges sold NFT (held in escrow) for auction proceeds
    address public immutable SELLER;

    // NFT_CONTRACT: address of contract account that governs NFT
    IERC721 public immutable NFT_CONTRACT;

    // NFT_ID: specific token Id of NFT within its governing contract
    uint256 public immutable NFT_ID;

    // timing

    // BASE_DURATION: length of the auction in seconds, measured from start()
    //  endTime will be set to block.timestamp + BASE_DURATION when start() is called
    uint256 public immutable BASE_DURATION;

    // ABSOLUTE_DURATION: maximum length of the auction in seconds, measured from start();
    //  endTimeAbsolute will be set to block.timestamp + ABSOLUTE_DURATION when start() is called
    uint256 public immutable ABSOLUTE_DURATION;

    // endTime: initial time when the auction is set to end; may be extended
    uint256 public endTime;

    // endTimeAbsolute: absolute maximum end time for the auction; endTime
    //  may only be extended up to endTimeAbsolute; after endTime can no
    //  longer be extended, sniping is allowed until endTimeAbsolute
    //  set during start(); zero before the auction has started
    uint256 public endTimeAbsolute;

    // EXTENSION_WINDOW: if the time until endTime is less than EXTENSION_WINDOW,
    //  then endTime is increased by extensionDuration
    uint256 public immutable EXTENSION_WINDOW;

    // EXTENSION_DURATION: amount of time to extend endTime after a bid within
    //  EXTENSION_DURATION
    uint256 public immutable EXTENSION_DURATION;

    // pricing

    // INITIAL_PRICE: minimum amount of first bid;
    //  if no bid is ever made, then the seller maintains ownership of the NFT
    uint256 public immutable INITIAL_PRICE;

    // MIN_BID_INCREMENT: minimum difference between the latest bid and the following bid
    //  note that units are in wei (name used on both Avalanche C-Chain and Ethereum)
    uint256 public immutable MIN_BID_INCREMENT;

    // current winner

    // maxBidder: address of current winning bidder;
    //  initialized to the zero address
    address public maxBidder;

    // maxBid: amount of the current highest bid in wei;
    //  initialized to 0
    uint256 public maxBid;

    // settlement

    // started: tracks whether start() has been called
    //  initialized to false; set to true after the seller transfers the NFT into escrow
    //  and the auction's clock begins
    bool public started;

    // settled: tracks whether settleAuction() has been called
    //  initialized to false; set to true after the auction has been finalized
    //  required to prevent double-sale
    bool public settled;

    // pendingReturns: tracks refunds owed to outbid participants;
    //  uses the pull-payment pattern to avoid pushing funds during bid()
    //  (which would risk reentrancy and griefing from malicious previous bidders)
    //  if the seller's sale proceeds cannot be immediately transferred, they too are
    //  are held here for later withdrawal
    mapping(address => uint256) public pendingReturns;

    // events

    // BidPlaced: emitted whenever a valid bid is accepted
    //  bidder: the address of the bidding account
    //  amount: value of bid in wei
    //  bidder is indexed for easy searching by a frontend UI
    event BidPlaced(address indexed bidder, uint256 amount);

    // AuctionExtended: emitted whenever the auction is extended by extensionWindow
    //  newEndTime: the revised end time of the auction
    event AuctionExtended(uint256 newEndTime);

    // AuctionSettled: emitted when the auction is settled
    //  winner: the address of the winning account; 0 if no valid bids are ever placed
    //  amount: value of winning bid in wei
    //  winner is indexed for easy searching by a frontend UI
    event AuctionSettled(address indexed winner, uint256 amount);

    // Withdrawal: emitted whenever an outbid account claims its refund
    //  bidder: the address of the withdrawing bidder
    //  amount: amount withdrawn, in wei
    //  bidder is indexed for easy searching by a frontend UI
    event Withdrawal(address indexed bidder, uint256 amount);

    // AuctionCreated: emitted whenever a new auction is created; this event allows
    //  indexers to discover the auction through event logs alone; not strictly necessary
    //  for this project, but useful as a demonstration
    //  seller: address of selling account
    //  nftContract: address of contracting governing auctioned NFT
    //  nftId: Id of NFT within its governing contract
    //  endTime: initial endTime of auction
    //  initialPrice: initial sale price of NFT
    //  seller, nftContract, and nftId are indexed for the convenience of frontend UIs
    event AuctionCreated(
        address indexed seller,
        address indexed nftContract,
        uint256 indexed nftId,
        uint256 baseDuration,
        uint256 initialPrice
    );

    // AuctionStarted: emitted when start() is called and the auction's clock begins
    //  endTime: the auction's initial scheduled end time
    event AuctionStarted(uint256 endTime);

    // initialization and launch

    // constructor: initializes auction parameters but does not escrow the NFT or start the clock;
    //  the seller must manually start the auction by calling start()
    constructor(
        address _nftContract,
        uint256 _nftId,
        uint256 _baseDuration,
        uint256 _absoluteDuration,
        uint256 _extensionWindow,
        uint256 _extensionDuration,
        uint256 _initialPrice,
        uint256 _minBidIncrement
    ) {
        // validate parameters
        require(_baseDuration > 0, "base duration must be positive");
        require(_absoluteDuration >= _baseDuration, "absolute duration must be at least as long as base duration");
        require(_extensionWindow <= _baseDuration, "extension window must not exceed base duration");
        require(_extensionDuration > 0, "extension duration must be positive");
        require(_initialPrice > 0, "initial price must be positive");
        require(_minBidIncrement > 0, "min bid increment must be positive");

        // assign immutables
        SELLER = msg.sender;
        NFT_CONTRACT = IERC721(_nftContract);
        NFT_ID = _nftId;
        BASE_DURATION = _baseDuration;
        ABSOLUTE_DURATION = _absoluteDuration;
        EXTENSION_WINDOW = _extensionWindow;
        EXTENSION_DURATION = _extensionDuration;
        INITIAL_PRICE = _initialPrice;
        MIN_BID_INCREMENT = _minBidIncrement;

        // emit AuctionCreated
        emit AuctionCreated(msg.sender, _nftContract, _nftId, _baseDuration, _initialPrice);
    }

    // start: called by the seller to escrow the NFT and begin the auction;
    //  requires the seller to have approved this contract for the specific NFT
    //  beforehand via the NFT contract's approve() function
    function start() external {
        require(msg.sender == SELLER, "only seller may start");
        require(!started, "auction has already been started");

        // set started = true and compute end times relative to now
        started = true;
        endTime = block.timestamp + BASE_DURATION;
        endTimeAbsolute = block.timestamp + ABSOLUTE_DURATION;

        // escrow the NFT
        NFT_CONTRACT.transferFrom(msg.sender, address(this), NFT_ID);

        emit AuctionStarted(endTime);
    }

    // core auction operations

    // bid: called by users to place a new bid
    //  the bid amount is the AVAX sent with the call (msg.value)
    //  if the bid is accepted, the previous high bidder's funds are credited to pendingReturns for later withdrawal

    function bid() external payable nonReentrant {
        // local variables
        uint256 effectiveBid; // total bid amount: msg.value + caller's existing pendingReturns
        uint256 newEndTime; // updated end time if bid placed within EXTENSION_WINDOW

        // verify auction is active
        require(started, "auction not started");
        require(block.timestamp < endTime, "auction ended");
        require(!settled, "auction already settled");

        // verify bidder is not seller
        require(msg.sender != SELLER, "seller cannot bid");

        // verify bidder is not already the max bidder (cannot outbid oneself)
        require(msg.sender != maxBidder, "already highest bidder");

        // compute effective bid: msg.value plus any existing pending refund;
        //  this is the amount being committed as the new bid
        effectiveBid = msg.value;
        if (pendingReturns[msg.sender] > 0) {
            effectiveBid += pendingReturns[msg.sender];
            pendingReturns[msg.sender] = 0;
        }

        // verify effective bid amount
        if (maxBidder == address(0)) {
            // no bids yet
            require(effectiveBid >= INITIAL_PRICE, "bid below initial price");
        } else {
            // new bids must exceed maxBid by at least MIN_BID_INCREMENT
            require(effectiveBid >= maxBid + MIN_BID_INCREMENT, "bid below minimum increment");
        }

        // increase the previous high bidder's refund within pendingReturns
        if (maxBidder != address(0)) {
            pendingReturns[maxBidder] += maxBid;
        }

        // update maxBidder and maxBid using the effective bid amount
        maxBidder = msg.sender;
        maxBid = effectiveBid;

        // extend auction if within EXTENSION_WINDOW
        if (endTime - block.timestamp < EXTENSION_WINDOW) {
            newEndTime = block.timestamp + EXTENSION_DURATION;
            if (newEndTime > endTimeAbsolute) {
                newEndTime = endTimeAbsolute;
            }
            if (newEndTime > endTime) {
                endTime = newEndTime;
                emit AuctionExtended(newEndTime);
            }
        }

        emit BidPlaced(msg.sender, effectiveBid);
    }

    // withdraw: called by outbid bidders to reclaim funds
    function withdraw() external nonReentrant {
        // local variables

        uint256 amount; // amount to refund
        bool success; // success of transfer

        // retrieve refund amount

        amount = pendingReturns[msg.sender];
        // attempting to return a 0 amount would be wasted gas
        require(amount > 0, "nothing to withdraw");

        // zero the caller's balance *before* sending
        //  avoid repeating the DAO incident
        pendingReturns[msg.sender] = 0;

        // send the funds
        (success,) = msg.sender.call{value: amount}("");
        require(success, "transfer failed");

        emit Withdrawal(msg.sender, amount);
    }

    // settleAuction: finalize the auction
    //  callable by anyone; the outcome depends only on the auction's state,
    //  not on who triggers it; may only be called successfully after endTime
    //  if there was a winning bid, transfers the NFT to the winner and the
    //  winning bid to the seller; if there was no bid, returns the NFT to
    //  the seller
    function settleAuction() external nonReentrant {
        // local variables
        bool success; // indicates whether proceeds were transferred to seller

        require(started, "auction not started");
        require(block.timestamp >= endTime, "auction not yet ended");
        require(!settled, "auction already settled");

        // mark settled before any external calls
        settled = true;

        if (maxBidder != address(0)) {
            // there was a winning bid:
            //  send proceeds to the seller, transfer NFT to the winner
            (success,) = SELLER.call{value: maxBid}("");
            // if funds could not be immediately transferred to seller,
            //  then hold them in pendingReturns for later withdrawal
            if (!success) {
                pendingReturns[SELLER] += maxBid;
            }

            NFT_CONTRACT.transferFrom(address(this), maxBidder, NFT_ID);
        } else {
            // no bids were placed: return the NFT to the seller
            NFT_CONTRACT.transferFrom(address(this), SELLER, NFT_ID);
        }

        emit AuctionSettled(maxBidder, maxBid);
    }

    // convenience functions

    // timeRemaining: seconds until the auction's current endTime
    //  returns 0 if the auction has ended, has not yet started, or has been settled
    function timeRemaining() external view returns (uint256) {
        if (!started || settled || block.timestamp >= endTime) {
            return 0;
        }
        return endTime - block.timestamp;
    }

    // minimumNextBid: the smallest valid amount of the next bid in wei
    //  if no bids have been placed, returns INITIAL_PRICE;
    //  otherwise returns maxBid + MIN_BID_INCREMENT
    function minimumNextBid() external view returns (uint256) {
        if (maxBidder == address(0)) {
            return INITIAL_PRICE;
        }
        return maxBid + MIN_BID_INCREMENT;
    }

    // minimumNextBidForCaller: the smallest msg.value the caller needs to send
    //  to place a valid next bid, accounting for any existing pendingReturns balance;
    //  returns 0 if the caller's existing balance already meets the minimum
    function minimumNextBidForCaller() external view returns (uint256) {
        uint256 minimum;
        if (maxBidder == address(0)) {
            minimum = INITIAL_PRICE;
        } else {
            minimum = maxBid + MIN_BID_INCREMENT;
        }

        uint256 existingBalance = pendingReturns[msg.sender];
        if (existingBalance >= minimum) {
            return 0;
        }
        return minimum - existingBalance;
    }

    // pendingRefund: amount in wei that the given account can withdraw;
    //  for outbid bidders this is the sum of their displaced bids;
    //  for the seller, this may be nonzero if a push payment failed during settlement
    function pendingRefund(address account) external view returns (uint256) {
        return pendingReturns[account];
    }

    // auctionStatus: a single call returning the auction's most relevant state;
    //  useful for frontends that want to render the full UI from one read
    //  isStarted: has start() been called
    //  isEnded: has the auction's endTime passed (or been settled)
    //  isSettled: has settleAuction() been called
    //  currentMaxBidder: address of the current high bidder (zero if none)
    //  currentMaxBid: amount of the current high bid in wei
    //  currentEndTime: the auction's current endTime
    function auctionStatus()
        external
        view
        returns (
            bool isStarted,
            bool isEnded,
            bool isSettled,
            address currentMaxBidder,
            uint256 currentMaxBid,
            uint256 currentEndTime
        )
    {
        isStarted = started;
        isEnded = started && (block.timestamp >= endTime || settled);
        isSettled = settled;
        currentMaxBidder = maxBidder;
        currentMaxBid = maxBid;
        currentEndTime = endTime;
    }
}
